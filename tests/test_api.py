def test_register_and_login(client):
    # 1. Register
    res = client.post("/auth/register", json={
        "username": "testuser",
        "password": "testpassword"
    })
    assert res.status_code == 201
    assert res.json() == {"message": "User registered successfully"}
    
    # 2. Duplicate registration should fail
    res_dup = client.post("/auth/register", json={
        "username": "testuser",
        "password": "testpassword"
    })
    assert res_dup.status_code == 400
    
    # 3. Login
    login_res = client.post("/auth/token", data={
        "username": "testuser",
        "password": "testpassword"
    })
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()

def test_admin_logs_rbac(client, db_session):
    # Register non-admin
    client.post("/auth/register", json={
        "username": "guest",
        "password": "guestpassword"
    })
    token = client.post("/auth/token", data={"username": "guest", "password": "guestpassword"}).json()["access_token"]
    
    # Non-admin access should be forbidden
    res = client.get("/admin/logs", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    
    # Register admin
    client.post("/auth/register", json={
        "username": "admin",
        "password": "adminpassword"
    })
    
    # Elevate via DB directly since we need an admin to make an admin
    from src.db.models import User
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    admin_user.groups = ["admin"]
    db_session.commit()

    admin_token = client.post("/auth/token", data={"username": "admin", "password": "adminpassword"}).json()["access_token"]
    
    # Admin access should succeed
    res_admin = client.get("/admin/logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    assert isinstance(res_admin.json(), dict)

from unittest.mock import patch, MagicMock

def test_ingest_endpoint(client, db_session):
    # Register & Login
    client.post("/auth/register", json={"username": "ingestor", "password": "pw"})
    from src.db.models import User
    user = db_session.query(User).filter(User.username == "ingestor").first()
    user.groups = ["admin"]
    db_session.commit()
    
    token = client.post("/auth/token", data={"username": "ingestor", "password": "pw"}).json()["access_token"]
    
    with patch("src.main.ingest_file_task.delay") as mock_celery:
        res = client.post("/ingest", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert "Dispatched" in res.json()["message"]
        assert mock_celery.called

def test_query_endpoint(client):
    from src.main import app, get_search_service, get_llm_service
    
    mock_search = MagicMock()
    mock_search.semantic_cache_lookup.return_value = None
    mock_search.search.return_value = [{"id": 1, "text": "foo", "filename": "bar", "source_type": "pdf", "allowed_groups": ["Public"]}]
    
    mock_llm = MagicMock()
    mock_llm.generate_answer.return_value = ("Hello World", ["bar"])
    
    app.dependency_overrides[get_search_service] = lambda: mock_search
    app.dependency_overrides[get_llm_service] = lambda: mock_llm
    
    try:
        # Login
        client.post("/auth/register", json={"username": "asker", "password": "pw"})
        token = client.post("/auth/token", data={"username": "asker", "password": "pw"}).json()["access_token"]
        
        # Run query
        res = client.post("/query", json={"query": "hello?"}, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["answer"] == "Hello World"
        assert data["citations"] == ["bar"]
        assert data["cached"] is False
    finally:
        app.dependency_overrides.pop(get_search_service, None)
        app.dependency_overrides.pop(get_llm_service, None)

def test_dlq_endpoints(client, db_session, mock_celery):
    from src.db.models import User, FailedIngestion
    # Register & make admin
    client.post("/auth/register", json={"username": "dlq_admin", "password": "pw"})
    admin_user = db_session.query(User).filter(User.username == "dlq_admin").first()
    admin_user.groups = ["admin"]
    
    # Create sample DLQ record
    failed_task = FailedIngestion(
        filepath="minio://documents/bad.pdf",
        source_type="pdf",
        error_message="Corrupted header",
        retry_count=3,
        status="FAILED"
    )
    db_session.add(failed_task)
    db_session.commit()
    
    token = client.post("/auth/token", data={"username": "dlq_admin", "password": "pw"}).json()["access_token"]
    
    # 1. Fetch DLQ
    res = client.get("/admin/dlq", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert data["records"][0]["error_message"] == "Corrupted header"
    
    # 2. Retry DLQ Task
    rec_id = data["records"][0]["id"]
    retry_res = client.post(f"/admin/dlq/{rec_id}/retry", headers={"Authorization": f"Bearer {token}"})
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "success"
    assert mock_celery.called

def test_upload_file_endpoint(client, db_session, mock_celery):
    client.post("/auth/register", json={"username": "uploader", "password": "pw"})
    token = client.post("/auth/token", data={"username": "uploader", "password": "pw"}).json()["access_token"]
    
    files = {"file": ("test_doc.md", b"# Sample Confluence Content", "text/markdown")}
    res = client.post("/ingest/file", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert mock_celery.called

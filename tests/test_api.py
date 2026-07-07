import pytest

def test_register_and_login(client):
    # 1. Register
    res = client.post("/auth/register", json={
        "username": "testuser",
        "password": "testpassword",
        "groups": ["Engineering"]
    })
    assert res.status_code == 201
    assert res.json() == {"message": "User registered successfully"}
    
    # 2. Duplicate registration should fail
    res_dup = client.post("/auth/register", json={
        "username": "testuser",
        "password": "testpassword",
        "groups": ["Engineering"]
    })
    assert res_dup.status_code == 400
    
    # 3. Login
    login_res = client.post("/auth/token", data={
        "username": "testuser",
        "password": "testpassword"
    })
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()

def test_admin_logs_rbac(client):
    # Register non-admin
    client.post("/auth/register", json={
        "username": "guest",
        "password": "guestpassword",
        "groups": ["Public"]
    })
    token = client.post("/auth/token", data={"username": "guest", "password": "guestpassword"}).json()["access_token"]
    
    # Non-admin access should be forbidden
    res = client.get("/admin/logs", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    
    # Register admin
    client.post("/auth/register", json={
        "username": "admin",
        "password": "adminpassword",
        "groups": ["admin"]
    })
    admin_token = client.post("/auth/token", data={"username": "admin", "password": "adminpassword"}).json()["access_token"]
    
    # Admin access should succeed
    res_admin = client.get("/admin/logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    assert isinstance(res_admin.json(), list)

def test_ingest_endpoint(client, mock_celery):
    # Register & Login
    client.post("/auth/register", json={"username": "ingestor", "password": "pw", "groups": ["admin"]})
    token = client.post("/auth/token", data={"username": "ingestor", "password": "pw"}).json()["access_token"]
    
    res = client.post("/ingest", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert "Dispatched" in res.json()["message"]
    assert mock_celery.called

def test_query_endpoint(client, mocker):
    # We mock the SearchService and LLMService internally to avoid loading heavy models during API tests
    mock_search = mocker.patch("src.main.get_search_service")
    mock_search.return_value.semantic_cache_lookup.return_value = None
    mock_search.return_value.search.return_value = [{"id": 1, "text": "foo", "filename": "bar", "source_type": "pdf", "allowed_groups": ["Public"]}]
    
    mock_llm = mocker.patch("src.main.get_llm_service")
    mock_llm.return_value.generate_answer.return_value = ("Hello World", ["bar"])
    
    # Login
    client.post("/auth/register", json={"username": "asker", "password": "pw", "groups": ["Public"]})
    token = client.post("/auth/token", data={"username": "asker", "password": "pw"}).json()["access_token"]
    
    # Run query
    res = client.post("/query", json={"query": "hello?"}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["answer"] == "Hello World"
    assert data["citations"] == ["bar"]
    assert data["cached"] is False

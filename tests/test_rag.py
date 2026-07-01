import pytest
import os
from src.ingestion.parsers import ConfluenceParser, SlackParser
from src.auth.jwt import get_password_hash, verify_password, create_access_token, decode_access_token

def test_confluence_parser():
    parser = ConfluenceParser()
    filepath = r"data/seed/confluence/sample_policy.md"
    
    # Check if file exists (it should in the workspace)
    assert os.path.exists(filepath), "Sample policy file not found"
    
    chunks = parser.parse(filepath)
    assert len(chunks) > 0, "Parser should return at least one chunk"
    
    # Check that it extracted the restricted access section and its specific ACL
    restricted_chunk = None
    for chunk in chunks:
        if "Restricted Access" in chunk["text_content"]:
            restricted_chunk = chunk
            break
            
    assert restricted_chunk is not None, "Could not find 'Restricted Access' section"
    assert "HR" in restricted_chunk["allowed_groups"], "Restricted chunk should have HR in allowed groups"
    assert "Management" in restricted_chunk["allowed_groups"], "Restricted chunk should have Management in allowed groups"
    
    # Check that other chunks have default 'Public' ACL
    for chunk in chunks:
        if "Restricted Access" not in chunk["text_content"]:
            assert chunk["allowed_groups"] == ["Public"], "Non-restricted chunks should be Public"

def test_slack_parser():
    parser = SlackParser()
    filepath = r"data/seed/slack/slack_export.json"
    
    assert os.path.exists(filepath), "Slack export file not found"
    
    chunks = parser.parse(filepath)
    assert len(chunks) == 1, "Should reconstruct 1 thread from the sample data"
    
    chunk = chunks[0]
    assert "U12345" in chunk["text_content"], "Should contain U12345 message"
    assert "U67890" in chunk["text_content"], "Should contain U67890 message"
    assert chunk["allowed_groups"] == ["Public"], "Default Slack ACL should be Public"

def test_jwt_auth():
    password = "secure_password_123"
    hashed = get_password_hash(password)
    
    assert verify_password(password, hashed), "Password verification failed"
    assert not verify_password("wrong_password", hashed), "Incorrect password verified successfully"
    
    data = {"sub": "john_doe", "groups": ["HR"]}
    token = create_access_token(data)
    
    decoded = decode_access_token(token)
    assert decoded.get("sub") == "john_doe", "Sub mismatch"
    assert decoded.get("groups") == ["HR"], "Groups mismatch"

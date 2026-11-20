import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.database import Base, engine
import os

client = TestClient(app)

def test_evaluation_unauthorized():
    response = client.post("/v1/evaluation/runs?model_version=v1")
    assert response.status_code == 401

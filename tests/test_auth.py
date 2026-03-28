def test_login_and_access_me(client, db_session):
    from app.core.config import get_settings
    from app.schemas.auth import UserCreate
    from app.services.auth_service import AuthService

    auth_service = AuthService(get_settings())
    auth_service.create_user(
        db_session,
        UserCreate(
            username="recepcion",
            full_name="Recepcion Test",
            email="recepcion@example.com",
            password="demo12345",
        ),
    )

    login_response = client.post(
        "/api/v1/auth/login",
        data={"username": "recepcion", "password": "demo12345"},
    )

    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "recepcion"

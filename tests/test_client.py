"""Tests for the Mender API clients (auth, inventory, deployments, preauth).

Los clientes aceptan una ``aiohttp.ClientSession`` inyectable; estos tests le
pasan una sesión falsa que registra las llamadas y devuelve respuestas
predefinidas, sin tocar la red.
"""

from types import SimpleNamespace

import aiohttp
import pytest

from mender_simulator.client.auth import AuthClient
from mender_simulator.client.base import BaseClient
from mender_simulator.client.deployments import (
    DeploymentsClient,
    DeploymentState,
)
from mender_simulator.client.exceptions import (
    AuthenticationError,
    DeviceNotAcceptedError,
)
from mender_simulator.client.inventory import InventoryClient
from mender_simulator.client.preauth import PreauthClient
from mender_simulator.utils.crypto import generate_rsa_keypair, verify_signature


# --------------------------------------------------------------------------- #
# Dobles de prueba para HTTP                                                   #
# --------------------------------------------------------------------------- #
class FakeResponse:
    """Respuesta HTTP falsa usable como async context manager."""

    def __init__(self, status=200, text="", json_data=None, headers=None):
        self.status = status
        self._text = text
        self._json = json_data
        self.headers = headers or {}

    async def text(self):
        return self._text

    async def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Sesión falsa: registra llamadas y devuelve una respuesta fija (o lanza)."""

    def __init__(self, response=None, exc=None):
        self.closed = False
        self.response = response
        self.exc = exc
        self.calls = []

    def _make(self, method):
        def _call(url, **kwargs):
            self.calls.append(SimpleNamespace(method=method, url=url, kwargs=kwargs))
            if self.exc is not None:
                raise self.exc
            return self.response

        return _call

    def __getattr__(self, name):
        if name in ("post", "get", "patch", "put", "head"):
            return self._make(name)
        raise AttributeError(name)

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture(scope="module")
def keypair():
    """Par RSA generado una vez por módulo (2048 basta para los tests)."""
    return generate_rsa_keypair(key_size=2048)


# --------------------------------------------------------------------------- #
# BaseClient                                                                   #
# --------------------------------------------------------------------------- #
class TestBaseClient:
    def test_strips_trailing_slash(self):
        client = BaseClient("https://mender.io/", session=FakeSession())
        assert client.server_url == "https://mender.io"

    async def test_injected_session_not_owned_and_reused(self):
        session = FakeSession()
        client = BaseClient("https://mender.io", session=session)
        assert client._owns_session is False
        await client._ensure_session()
        assert client._session is session

    async def test_close_does_not_close_injected_session(self):
        session = FakeSession()
        client = BaseClient("https://mender.io", session=session)
        await client.close()
        assert session.closed is False

    async def test_ensure_session_creates_when_missing(self):
        client = BaseClient("https://mender.io")
        await client._ensure_session()
        assert client._session is not None
        assert client._owns_session is True
        await client.close()
        assert client._session.closed is True

    async def test_async_context_manager(self):
        session = FakeSession()
        async with BaseClient("https://mender.io", session=session) as client:
            assert client._session is session
        assert session.closed is False  # sesión inyectada: no se cierra


# --------------------------------------------------------------------------- #
# AuthClient                                                                   #
# --------------------------------------------------------------------------- #
class TestAuthClient:
    async def test_authenticate_success_returns_token_and_signs(self, keypair):
        private_pem, public_pem = keypair
        session = FakeSession(FakeResponse(status=200, text="jwt-token-123"))
        client = AuthClient("https://mender.io", "tenant-abc", session=session)

        token = await client.authenticate({"mac": "aa:bb"}, public_pem, private_pem)

        assert token == "jwt-token-123"
        call = session.last
        assert call.method == "post"
        assert call.url.endswith("/authentication/auth_requests")
        # El cuerpo enviado va firmado y la firma verifica con la pubkey.
        body = call.kwargs["data"]
        signature = call.kwargs["headers"]["X-MEN-Signature"]
        assert verify_signature(public_pem, body.encode("utf-8"), signature)

    async def test_authenticate_401_raises_device_not_accepted(self, keypair):
        private_pem, public_pem = keypair
        session = FakeSession(FakeResponse(status=401, text="pending"))
        client = AuthClient("https://mender.io", "t", session=session)
        with pytest.raises(DeviceNotAcceptedError):
            await client.authenticate({}, public_pem, private_pem)

    async def test_authenticate_server_error_returns_none(self, keypair):
        private_pem, public_pem = keypair
        session = FakeSession(FakeResponse(status=500, text="boom"))
        client = AuthClient("https://mender.io", "t", session=session)
        assert await client.authenticate({}, public_pem, private_pem) is None

    async def test_authenticate_client_error_returns_none(self, keypair):
        private_pem, public_pem = keypair
        session = FakeSession(exc=aiohttp.ClientError("net down"))
        client = AuthClient("https://mender.io", "t", session=session)
        assert await client.authenticate({}, public_pem, private_pem) is None

    async def test_check_token_valid(self):
        session = FakeSession(FakeResponse(status=200))
        client = AuthClient("https://mender.io", "t", session=session)
        assert await client.check_token_valid("tok") is True

    async def test_check_token_invalid_on_401(self):
        session = FakeSession(FakeResponse(status=401))
        client = AuthClient("https://mender.io", "t", session=session)
        assert await client.check_token_valid("tok") is False

    async def test_check_token_client_error_returns_false(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = AuthClient("https://mender.io", "t", session=session)
        assert await client.check_token_valid("tok") is False


# --------------------------------------------------------------------------- #
# InventoryClient                                                              #
# --------------------------------------------------------------------------- #
class TestInventoryClient:
    def test_format_inventory_types(self):
        client = InventoryClient("https://mender.io", session=FakeSession())
        formatted = client._format_inventory(
            {"tags": ["a", "b"], "active": True, "count": 3}
        )
        by_name = {item["name"]: item["value"] for item in formatted}
        assert by_name["tags"] == ["a", "b"]  # listas tal cual
        assert by_name["active"] == "true"  # bool en minúscula
        assert by_name["count"] == "3"  # el resto como str

    async def test_update_inventory_success(self):
        session = FakeSession(FakeResponse(status=200))
        client = InventoryClient("https://mender.io", session=session)
        assert await client.update_inventory("tok", {"a": 1}) is True
        assert session.last.method == "patch"

    async def test_update_inventory_401_raises(self):
        session = FakeSession(FakeResponse(status=401))
        client = InventoryClient("https://mender.io", session=session)
        with pytest.raises(AuthenticationError):
            await client.update_inventory("tok", {"a": 1})

    async def test_update_inventory_server_error_returns_false(self):
        session = FakeSession(FakeResponse(status=500, text="err"))
        client = InventoryClient("https://mender.io", session=session)
        assert await client.update_inventory("tok", {"a": 1}) is False

    async def test_update_inventory_client_error_returns_false(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = InventoryClient("https://mender.io", session=session)
        assert await client.update_inventory("tok", {"a": 1}) is False

    async def test_get_inventory_parses_list_to_dict(self):
        payload = [{"name": "device_type", "value": "tcu"}, {"name": "x", "value": "1"}]
        session = FakeSession(FakeResponse(status=200, json_data=payload))
        client = InventoryClient("https://mender.io", session=session)
        assert await client.get_inventory("tok") == {"device_type": "tcu", "x": "1"}

    async def test_get_inventory_non_200_returns_none(self):
        session = FakeSession(FakeResponse(status=404))
        client = InventoryClient("https://mender.io", session=session)
        assert await client.get_inventory("tok") is None

    async def test_get_inventory_client_error_returns_none(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = InventoryClient("https://mender.io", session=session)
        assert await client.get_inventory("tok") is None


# --------------------------------------------------------------------------- #
# DeploymentsClient                                                            #
# --------------------------------------------------------------------------- #
class TestDeploymentsClient:
    async def test_check_for_deployment_parses_payload(self):
        payload = {
            "id": "dep-1",
            "artifact": {
                "artifact_name": "tcu-v2",
                "source": {"uri": "https://s3/artifact", "size": 1234},
            },
        }
        session = FakeSession(FakeResponse(status=200, json_data=payload))
        client = DeploymentsClient("https://mender.io", session=session)

        deployment = await client.check_for_deployment("tok", {"device_type": "tcu"})

        assert deployment is not None
        assert deployment.id == "dep-1"
        assert deployment.artifact_name == "tcu-v2"
        assert deployment.artifact_uri == "https://s3/artifact"
        assert deployment.artifact_size == 1234

    async def test_check_for_deployment_204_returns_none(self):
        session = FakeSession(FakeResponse(status=204))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.check_for_deployment("tok", {}) is None

    async def test_check_for_deployment_401_raises(self):
        session = FakeSession(FakeResponse(status=401))
        client = DeploymentsClient("https://mender.io", session=session)
        with pytest.raises(AuthenticationError):
            await client.check_for_deployment("tok", {})

    async def test_check_for_deployment_server_error_returns_none(self):
        session = FakeSession(FakeResponse(status=500, text="err"))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.check_for_deployment("tok", {}) is None

    async def test_check_for_deployment_client_error_returns_none(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.check_for_deployment("tok", {}) is None

    async def test_update_status_success_sends_state_value(self):
        session = FakeSession(FakeResponse(status=204))
        client = DeploymentsClient("https://mender.io", session=session)
        ok = await client.update_deployment_status(
            "tok", "dep-1", DeploymentState.INSTALLING, substate="flashing"
        )
        assert ok is True
        assert session.last.method == "put"
        assert session.last.kwargs["json"] == {
            "status": "installing",
            "substate": "flashing",
        }

    async def test_update_status_error_returns_false(self):
        session = FakeSession(FakeResponse(status=500, text="err"))
        client = DeploymentsClient("https://mender.io", session=session)
        ok = await client.update_deployment_status(
            "tok", "dep-1", DeploymentState.SUCCESS
        )
        assert ok is False

    async def test_update_status_client_error_returns_false(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = DeploymentsClient("https://mender.io", session=session)
        ok = await client.update_deployment_status(
            "tok", "dep-1", DeploymentState.SUCCESS
        )
        assert ok is False

    async def test_send_logs_success(self):
        session = FakeSession(FakeResponse(status=204))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.send_deployment_logs("tok", "dep-1", []) is True

    async def test_send_logs_error_returns_false(self):
        session = FakeSession(FakeResponse(status=400, text="bad"))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.send_deployment_logs("tok", "dep-1", []) is False

    async def test_send_logs_client_error_returns_false(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.send_deployment_logs("tok", "dep-1", []) is False

    async def test_download_artifact_accessible(self):
        session = FakeSession(
            FakeResponse(status=200, headers={"Content-Length": "999"})
        )
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.download_artifact("tok", "https://s3/a") is True
        assert session.last.method == "head"

    async def test_download_artifact_not_accessible(self):
        session = FakeSession(FakeResponse(status=403))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.download_artifact("tok", "https://s3/a") is False

    async def test_download_artifact_client_error_returns_false(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = DeploymentsClient("https://mender.io", session=session)
        assert await client.download_artifact("tok", "https://s3/a") is False


# --------------------------------------------------------------------------- #
# PreauthClient                                                                #
# --------------------------------------------------------------------------- #
class TestPreauthClient:
    async def test_preauthorize_created(self):
        session = FakeSession(FakeResponse(status=201))
        client = PreauthClient("https://mender.io", "pat", session=session)
        assert await client.preauthorize_device({"mac": "aa"}, "pub") is True
        assert session.last.method == "post"
        assert session.last.kwargs["headers"]["Authorization"] == "Bearer pat"

    async def test_preauthorize_conflict_is_success(self):
        session = FakeSession(FakeResponse(status=409))
        client = PreauthClient("https://mender.io", "pat", session=session)
        assert await client.preauthorize_device({"mac": "aa"}, "pub") is True

    async def test_preauthorize_error_returns_false(self):
        session = FakeSession(FakeResponse(status=500, text="err"))
        client = PreauthClient("https://mender.io", "pat", session=session)
        assert await client.preauthorize_device({"mac": "aa"}, "pub") is False

    async def test_preauthorize_client_error_returns_false(self):
        session = FakeSession(exc=aiohttp.ClientError("down"))
        client = PreauthClient("https://mender.io", "pat", session=session)
        assert await client.preauthorize_device({"mac": "aa"}, "pub") is False

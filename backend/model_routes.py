"""Platform model HTTP surface; app middleware enforces auth and CSRF."""
from fastapi import APIRouter, Request

from . import platform_models as models, store as s
from . import provider_presets

router = APIRouter()


async def _body(request):
    try:
        value = await request.json()
    except ValueError:
        raise ValueError('配置必须为 JSON 对象') from None
    if not isinstance(value, dict):
        raise ValueError('配置必须为 JSON 对象')
    return value


def _id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError('配置标识无效')
    return value


@router.get('/api/models')
def catalog():
    return models.catalog()


@router.get('/api/admin/model-providers')
def providers():
    return models.admin_providers()


@router.post('/api/admin/model-providers')
async def create_provider(request: Request):
    return models.save_provider(s.uid('provider-'), await _body(request))


@router.put('/api/admin/model-providers/{provider_id}')
async def update_provider(provider_id: str, request: Request):
    return models.save_provider(_id(provider_id), await _body(request))


@router.post('/api/admin/model-providers/{provider_id}/check')
def check_provider(provider_id: str):
    return models.check_provider(_id(provider_id))


@router.post('/api/admin/model-providers/{provider_id}/credentials/{credential_id}/revoke')
def revoke_provider_key(provider_id: str, credential_id: str):
    return models.revoke_credential(_id(provider_id), _id(credential_id))


@router.get('/api/admin/models')
def admin_models():
    return models.admin_models()


@router.get('/api/admin/provider-presets')
def presets():
    return provider_presets.catalog()


@router.post('/api/admin/provider-presets/{preset_id}')
async def save_preset(preset_id: str, request: Request):
    return provider_presets.save(_id(preset_id), await _body(request))


@router.post('/api/admin/models')
async def create_model(request: Request):
    return models.save_model(s.uid('model-'), await _body(request))


@router.put('/api/admin/models/{model_id}')
async def update_model(model_id: str, request: Request):
    return models.save_model(_id(model_id), await _body(request))

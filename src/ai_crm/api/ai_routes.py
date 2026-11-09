from ..ai.use_cases import AIUseCaseService
from .ai_endpoints import router

__all__ = ["router", "service"]

# The endpoints in ai_endpoints read this module attribute on every call.
service = AIUseCaseService()

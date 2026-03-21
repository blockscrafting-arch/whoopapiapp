from fastapi import APIRouter

from app.deps import CurrentUser

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("")
async def get_profile(user: CurrentUser) -> dict:
    """Профиль из данных, сохранённых при OAuth (без лишнего запроса к WHOOP)."""
    return {
        "user_id": str(user.id),
        "whoop_user_id": user.whoop_user_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }

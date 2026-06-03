"""HTTP-API модуля Marketing. Монтируется под префиксом ``/marketing``."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from modules.marketing.models import Campaign
from modules.marketing.schemas import CampaignCreate, CampaignOut

router = APIRouter(tags=["marketing"])


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(session: AsyncSession = Depends(get_session)):
    """Маркетинговые кампании."""
    return (await session.execute(select(Campaign).order_by(Campaign.id.desc()))).scalars().all()


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(payload: CampaignCreate, session: AsyncSession = Depends(get_session)):
    """Создать кампанию."""
    obj = Campaign(
        name=payload.name,
        channel=payload.channel,
        budget=Decimal(str(payload.budget)),
        leads=payload.leads,
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.post("/campaigns/{campaign_id}/launch", response_model=CampaignOut)
async def launch_campaign(
    campaign_id: int,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
):
    """Запустить кампанию: привлечённые лиды попадают в воронку CRM (marketing → sales)."""
    obj = await session.get(Campaign, campaign_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    core.event_bus.emit(
        session,
        "marketing.campaign.launched",
        {"name": obj.name, "leads": obj.leads, "channel": obj.channel},
    )
    await session.commit()
    return obj

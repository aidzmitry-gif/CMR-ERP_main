from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.knowledge import routes as knowledge
from modules.knowledge.models import Course, CourseEnrollment
from modules.knowledge.schemas import CourseCreate, CourseEnrollmentCreate, CourseEnrollmentPatch
from modules.knowledge.schemas import StageUpdate as CourseStage
from modules.legal import routes as legal
from modules.legal.models import LegalCase
from modules.legal.schemas import LegalCaseCreate
from modules.legal.schemas import StageUpdate as LegalStage
from modules.marketing import routes as marketing
from modules.marketing.models import Campaign
from modules.marketing.schemas import CampaignCreate
from modules.service import routes as service
from modules.service.models import ServiceRequest, Ticket
from modules.service.schemas import ServiceRequestCreate, ServiceRequestPatch, TicketCreate


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *, gets=None, results=()):
        self.gets = gets or {}
        self.results = list(results)
        self.added = []
        self.commits = 0
        self.refreshed = []

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 60 + len(self.added)
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 60

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    async def get(self, model, identity):
        return self.gets.get((model, identity), self.gets.get(identity))

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((event_type, payload))


def test_small_module_card_mappers_cover_stateful_ui_contracts():
    claim = legal._to_card(SimpleNamespace(
        id=1, number="", company="Альфа", title="Долг", amount=1000,
        urgency="Срочно", owner="Юрист", stage="claim", due_date="2026-09-20", next_step="Письмо",
    ))
    assert claim.code == "ДЕЛО-1" and claim.details[1]["v"] == "80 ₽"
    assert claim.action == "Открыть документ →"
    inbox = legal._to_card(SimpleNamespace(
        id=2, number="L-2", company="Бета", title="", amount=0,
        urgency="Обычный", owner="", stage="inbox", due_date=None, next_step="",
    ))
    assert inbox.action == "" and inbox.details == []

    assert knowledge._to_card(SimpleNamespace(
        id=1, number="", title="Курс", description="Описание", kind="Видео", duration=30,
        progress=0, audience="Все", stage="trial",
    )).action == "Начать"
    assert knowledge._to_card(SimpleNamespace(
        id=2, number="K-2", title="Курс", description="", kind="", duration=0,
        progress=50, audience="", stage="trial",
    )).state == "В процессе"
    assert knowledge._to_card(SimpleNamespace(
        id=3, number="K-3", title="Курс", description="", kind="", duration=0,
        progress=100, audience="", stage="trial",
    )).action == "Повторить"


@pytest.mark.asyncio
async def test_legal_case_and_knowledge_course_crud_cover_create_update_and_not_found():
    legal_session = Session()
    case = await legal.create_case(LegalCaseCreate(company="Альфа", amount=100), legal_session)
    assert isinstance(case, LegalCase) and case.number == "ДЕЛО-2026-0060"
    case_session = Session(gets={(LegalCase, 60): case})
    assert await legal.update_case(60, LegalStage(stage="court"), case_session) is case
    assert case.stage == "court" and case_session.commits == 1
    with pytest.raises(HTTPException) as missing:
        await legal.update_case(404, LegalStage(stage="court"), Session())
    assert missing.value.status_code == 404

    course_session = Session()
    course = await knowledge.create_course(CourseCreate(title="Охрана труда"), course_session)
    assert isinstance(course, Course) and course.number == "КУРС-060"
    course_session = Session(gets={(Course, 60): course})
    await knowledge.update_course(60, CourseStage(stage="development"), course_session)
    assert course.stage == "development"

    enrollment_session = Session()
    enrollment = await knowledge.create_enrollment(
        CourseEnrollmentCreate(course_id=60, employee_name="Иван"), enrollment_session
    )
    assert isinstance(enrollment, CourseEnrollment)
    enrollment_session = Session(gets={(CourseEnrollment, 60): enrollment})
    completed = await knowledge.patch_enrollment(60, CourseEnrollmentPatch(status="completed"), enrollment_session)
    assert completed.status == "completed" and completed.progress == 100 and completed.completed_at
    assert await knowledge.get_enrollment(60, enrollment_session) is enrollment
    with pytest.raises(HTTPException) as no_enrollment:
        await knowledge.get_enrollment(404, Session())
    assert no_enrollment.value.status_code == 404


@pytest.mark.asyncio
async def test_service_and_marketing_routes_persist_dtos_and_events():
    ticket_session = Session()
    ticket = await service.create_ticket(TicketCreate(customer="Альфа", subject="Вопрос"), ticket_session)
    assert isinstance(ticket, Ticket) and ticket.status == "open"

    request_session = Session()
    request_obj = await service.create_request(ServiceRequestCreate(title="Ремонт"), request_session)
    assert isinstance(request_obj, ServiceRequest) and request_obj.title == "Ремонт"
    request_session = Session(results=[Result([request_obj])])
    assert await service.get_request(60, request_session) is request_obj
    request_session = Session(results=[Result([request_obj])])
    patched = await service.patch_request(60, ServiceRequestPatch(status="done", priority="high"), request_session)
    assert (patched.status, patched.priority) == ("done", "high")
    with pytest.raises(HTTPException) as missing:
        await service.get_request(404, Session(results=[Result()]))
    assert missing.value.status_code == 404

    campaign_session = Session()
    campaign = await marketing.create_campaign(
        CampaignCreate(name="Осень", channel="ads", budget=125.5, leads=3, utm_source="google"), campaign_session
    )
    assert campaign.model_dump()["budget"] == "125.5"
    bus = Bus()
    result = await marketing.launch_campaign(60, SimpleNamespace(event_bus=bus), Session(gets={(Campaign, 60): SimpleNamespace(
        id=60, name="Осень", channel="ads", budget=Decimal("125.5"), leads=3,
        utm_source="google", utm_medium="cpc", utm_campaign="fall", goal="leads",
    )}))
    assert result.id == 60 and bus.events[0][0] == "marketing.campaign.launched"
    with pytest.raises(HTTPException) as no_campaign:
        await marketing.launch_campaign(404, SimpleNamespace(event_bus=bus), Session())
    assert no_campaign.value.status_code == 404


@pytest.mark.asyncio
async def test_list_routes_apply_filters_and_project_campaign_attribution():
    courses = [SimpleNamespace(id=1)]
    assert await knowledge.list_courses(Session(results=[Result(courses)])) == courses
    assert await knowledge.list_enrollments("Иван", "assigned", Session(results=[Result(courses)])) == courses

    cases = [SimpleNamespace(id=1)]
    assert await legal.list_cases(Session(results=[Result(cases)])) == cases

    requests = [SimpleNamespace(id=1)]
    assert await service.list_requests("open", Session(results=[Result(requests)])) == requests
    assert await service.list_tickets(Session(results=[Result(requests)])) == requests

    campaigns = [SimpleNamespace(
        id=1, name="Осень", channel="ads", budget=Decimal("10"), leads=2,
        utm_source="google", utm_medium="cpc", utm_campaign="fall", goal="leads",
    )]
    attribution = await marketing.campaigns_attribution(Session(results=[Result(campaigns)]))
    assert attribution[0].model_dump()["budget"] == "10"
    listed = await marketing.list_campaigns(Session(results=[Result(campaigns)]))
    assert listed[0].utm_source == "google"

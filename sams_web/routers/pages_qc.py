"""Generic QC sign-off routes (`qc_signoff.py`).

`POST /qc/signoffs` signs one subject's unsigned set; `GET /qc/signoffs/{id}`
is the printable record for the audit binder. Neither knows which kind of
check it is — the subject handler supplies the description and the body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from sams_web.dependencies import get_service
from sams_web.qc_signoff import QcSignoffs, signoff_subjects
from sams_web.routers.pages_ea_checks import redirect_with, safe_return_url
from sams_web.routers.pages_shared import templates
from sams_web.services import SamsService

router = APIRouter()


@router.post("/qc/signoffs")
async def qc_signoff_create(request: Request, service: SamsService = Depends(get_service)):
    form = await request.form()
    subject_type = str(form.get("subject_type") or "")
    subject = signoff_subjects().get(subject_type)
    next_url = safe_return_url(str(form.get("next") or ""), subject.return_url if subject else "/")
    outcome = QcSignoffs(service).sign(
        subject_type=subject_type,
        subject_key=str(form.get("subject_key") or ""),
        period_to=str(form.get("period_to") or ""),
        signer=str(form.get("signer") or ""),
        verdict=str(form.get("verdict") or ""),
        comment=str(form.get("comment") or ""),
    )
    if outcome.success:
        return redirect_with(next_url, {"signoff_notice": outcome.message}, "qc-signoffs")
    return redirect_with(next_url, {"signoff_error": outcome.error or "Could not sign off."})


@router.get("/qc/signoffs/{signoff_id}")
def qc_signoff_print(signoff_id: int, request: Request, service: SamsService = Depends(get_service)):
    if service.repo.missing_qc_tables():
        raise HTTPException(status_code=404, detail="QC sign-off tables are not set up yet.")
    detail = QcSignoffs(service).detail(signoff_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Sign-off {signoff_id} not found.")
    return templates.TemplateResponse(
        request,
        "qc_signoff_print.html",
        {"request": request, "title": f"QC sign-off #{signoff_id}", "signoff": detail},
    )

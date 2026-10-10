"""Conservative evidence/rights publication gate for an event occurrence.
No event is approved without a human editorial decision. This module does not publish.
"""
from __future__ import annotations
import json
from pathlib import Path

REGISTRY=Path(__file__).resolve().parents[1]/'docs/source_registry.json'

def evaluate(record, occurrence, *, human_approved=False, rights_registry=None):
    rights_registry=rights_registry or json.loads(REGISTRY.read_text())
    blockers=[]
    src=record.get('source')
    license_record=rights_registry.get(src)
    if not license_record or license_record['data_reuse_status']=='unconfirmed_for_bulk_ingestion':
        blockers.append('SOURCE_REUSE_NOT_RESOLVED')
    if record.get('eligibility')=='exclude':blockers.append('OUTSIDE_PRD')
    if not human_approved:blockers.append('HUMAN_APPROVAL_REQUIRED')
    if record.get('kind') in ('program','service','course'):blockers.append('PROGRAM_OR_NON_EVENT_NEEDS_SPLIT_OR_EXCLUSION')
    if not occurrence.get('date') or not occurrence.get('time'):blockers.append('OCCURRENCE_DATE_TIME_UNVERIFIED')
    if occurrence.get('venue_status')!='verified':blockers.append('OCCURRENCE_VENUE_UNVERIFIED')
    if occurrence.get('primary_evidence_status')!='verified':blockers.append('PRIMARY_EVIDENCE_REQUIRED')
    if not occurrence.get('primary_evidence_url','').startswith('https://'):blockers.append('PRIMARY_SOURCE_URL_REQUIRED')
    if not occurrence.get('attribution'):blockers.append('SOURCE_ATTRIBUTION_REQUIRED')
    if not occurrence.get('source_checked_on'):blockers.append('LAST_VERIFIED_DATE_REQUIRED')
    if occurrence.get('approximate_source_end') and not occurrence.get('approximate_date_disclosed'):
        blockers.append('UNCERTAINTY_NOT_DISCLOSED')
    if occurrence.get('price_label')=='free' and occurrence.get('price_evidence_status')!='verified':
        blockers.append('FREE_PRICE_UNVERIFIED')
    if occurrence.get('image_used') and not occurrence.get('image_rights_verified'):
        blockers.append('THIRD_PARTY_IMAGE_RIGHTS_NOT_VERIFIED')
    return {'can_publish':len(blockers)==0,'blockers':sorted(set(blockers)),'reviewed_by_human':bool(human_approved)}

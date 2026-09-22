# NYC 311 Incremental Pipeline

Incremental ELT pipeline for NYC 311 Service Requests — Python + PostgreSQL + Airflow, with UPSERT-based loading and data quality checks.

## The problem
NYC's 311 system receives thousands of new service requests daily, and existing requests get updated as they're worked (status changes, closures). A naive full-refresh load doesn't scale and can't track those updates. This project builds a pipeline that loads only new/changed data, cleans it, and stays correct even if a run fails or is repeated.

## Dataset
[NYC 311 Service Requests from 2020 to Present](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9) (NYC Open Data / Socrata)

## Architecture
Socrata API → raw landing → Postgres staging → SQL transform/UPSERT → star schema (fact_service_requests + dims) → Airflow orchestration

## Status
- [x] Repo scaffolding (venv, .gitignore, requirements.txt)
- [ ] Data exploration
- [ ] Schema design + ADRs
- [ ] Initial backfill
- [ ] Incremental load logic
- [ ] Data quality checks
- [ ] Airflow DAG
- [ ] Failure testing
- [ ] Architecture diagram
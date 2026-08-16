# MaxKB HR ATS

This repository is a **slimmed MaxKB v2 fork**: the upstream enterprise RAG knowledge-base core is kept, and a multi-tenant HR recruitment workspace (ATS) is embedded in `apps/hr`.

The product direction is:

```text
MaxKB RAG core + traditional ATS workflow + propose-confirm-execute Agent
```

## Repository status

- RAG pipeline: **delivered** (pgvector + tsvector, RRF, rerank, Small-to-Big).
- ATS: current code is a legacy fixed state machine; the target model is an `Application + JobStage + StageHistory` design.
- Agent: designed, not implemented yet.

## Authoritative documents

| Document | Purpose |
|---|---|
| `docs/PRD.md` | Product baseline |
| `docs/ATS-STATE-MACHINE-V2.md` | Target ATS design |
| `docs/ATS-OPENSOURCE-REFERENCE.md` | Traditional open-source ATS research |
| `docs/ATS-DESIGN-SPEC.md` | Current code facts, migration reference only |
| `docs/PRD-AGENT-RAG.md` | Agent + RAG design |
| `docs/RAG-V2-DESIGN.md` | Delivered resume RAG design |

## Quick start

See `README-hr.md` and `CLAUDE.md`.

## License

GPL-3.0, inherited from MaxKB. This fork must remain GPL-3.0.

# QUFO architecture

The browser uses a same-origin FastAPI application. SQLite stores users, sessions, original uploads, text passages, structured contributions, generated report snapshots, and export approval history.

All access paths resolve the current authenticated user before selecting company/team/private material. Related-source calculations and retrieval operate on that permitted set. Administrators have full workspace access; other roles see company material, their own submissions, and their own team's material.

Uploads are read with a 5 MB limit, validated by format, converted to text, split into bounded passages, and deduplicated within the owner's visibility boundary. Original bytes remain available for download. Failure responses describe unsupported formats, unreadable text, or file limits.

Text and semantic retrieval are combined on demand. Embeddings are computed in bounded CPU batches and cached in SQLite by model configuration and text hash. Only authorized source passages participate in retrieval. The model receives the top two passages, while the interface exposes up to four retrieved passages. Lexical alignment assigns citations to the supplied context and rejects unsupported numbers. It does not prove semantic entailment. Invalid output falls back to labeled excerpts.

Reports use deterministic extraction, user-recorded priorities/pins/statuses, source dates, and audience-specific ordering. Explicit document signals identify deadline, completion, issue, requirement, and decision sentences. They remain source-linked findings, not automatically assigned official tasks. Related documents use shared text terms; links do not imply causation.

Time and cost are sums of recorded entries. An absent value is not a measured zero. Cost entries use INR in this release. There is no inferred ROI, internal Microsoft budget, or invented employee workload.

The scheduler prepares daily and Friday weekly snapshots after 18:00 Asia/Kolkata when the app is running. The report-history endpoint exposes the current user's snapshot metadata. Interactive reports are recalculated from currently permitted data.

The Windows launcher starts the app hidden, waits for its health endpoint, and opens the browser. It reuses an existing healthy QUFO process. Model preparation is an explicit one-time operation and never happens during a chat request.

## Future scaling

Replace in-memory corpus embedding with cached/versioned embeddings and a persistent vector index, add migrations and job queues, and evaluate larger models. Before network exposure add SSO or managed account provisioning, TLS, robust audit/access administration, backups, process supervision, and deployment-specific abuse controls. These are not claimed as implemented.

## Conversational and chronology handling

The chat engine resolves explicit collection names, previous-turn source IDs, or a dominant collection for short questions. It stores session-scoped context without treating previous generated answers as factual evidence. Dates and recorded work status use an evidence-driven path; ordinary technical explanations use retrieval and the language model. Official documentation update dates cannot become product release dates. Open issues come from explicit contribution statuses; source limitations remain labeled historical documentation context.

## Hardware acceleration

The inference runtime selects CUDA automatically when available and moves both model weights and token tensors to that device. Sentence embeddings use the same selection when a cached vector is missing. CPU-only machines retain the CPU path. One inference lock prevents overlapping model jobs; GPU memory can retain loaded weights between requests, with no continuous inference work while idle. Runtime diagnostics report actual parameter and encoder devices. The model and retrieval policies are unchanged by device selection.

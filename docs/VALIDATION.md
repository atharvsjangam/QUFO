# Verification

- 40 automated workflow/security tests passed.
- Browser workflow passed: sign-in, page navigation, document upload, contribution creation and status editing, audience selection, approved export download, mobile overflow check, and no page JavaScript errors.
- Four official Microsoft source URLs returned HTTP 200.
- 28/28 curated retrieval checks passed: the expected source category appears in the top three results for supported questions, and three unrelated questions abstain. The expanded set includes SSO, consent, Live Share, tabs, manifests, publishing failures, webhooks, and device permissions.
- A real local model request returned an evidence-linked Teams architecture synthesis in approximately 26 seconds, including initial model loading. The actual browser chat check also passed with citations, the evidence viewer, and connected documents. This is a single-machine observation, not a latency guarantee or a general quality benchmark.

The retrieval question set and individual outcomes are saved in [retrieval-results.json](retrieval-results.json). The suite measures retrieval and application behavior; it does not establish that every generated claim is correct. QUFO keeps retrieved passages visible for verification.

Screenshots are in [screenshots](screenshots/). AI-generated answer and evidence screenshots are captured separately from ordinary navigation checks.

## Reproduce

Run the application, then:

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe scripts/evaluate.py
npm ci
npm run test:ui
node scripts/check-ai-ui.cjs
```

Browser checks require Playwright Chromium; install it with `npx playwright install chromium` if it is missing. Browser workflow fixtures are removed through application endpoints. Tests use temporary databases; the retrieval check uses the supplied source collection.

## Conversation regressions

The exact reported start/latest/challenges questions are covered. Start answers distinguish development from preview; release milestones are selected chronologically without treating documentation revisions as releases. Challenge answers separate open submitted issues from dated source limitations. Context persists across turns within the signed-in session, respects current permissions, and can be reset. Semantic vectors are cached and reused.

The installed source collection now contains 23 full official documents plus four notes, totaling 43,811 words. See the source manifest for pinned revisions, upstream licensing and transformations.

Expanded-data browser validation passed: all five reported questions, conversation reset, full-document attribution, a real generated resource-specific-consent answer with evidence, and mobile chat layout. The technical answer took approximately 24 seconds on this machine.

## GPU verification

PyTorch 2.8.0+cu128 detected the NVIDIA RTX 4060 Laptop GPU. Actual CUDA tensor computation passed. QUFO reported both language-model parameters and the sentence encoder on cuda:0. The same resource-specific-consent question took 9.569 seconds cold and 1.893/2.102 seconds warm, compared with the prior 23.971-second CPU observation. These are separate cold/warm observations on one machine, not a general latency guarantee. Details: [GPU performance](gpu-performance.json).

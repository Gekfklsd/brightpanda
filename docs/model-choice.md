# Model choice

Run 16 Nov 2026. 27 resolved binary questions every arm answered, opened after 28 Sep 2026 (source: manifold), no research, median of 1 run(s).
Cost of this test: $4.06 (OpenRouter key usage).

| Arm | Baseline score (higher better) | Brier (lower better) | Difference from first arm, 90% range |
|---|---|---|---|
| openrouter/openai/gpt-5.4 / ours | -40.1 | 0.340 | reference |
| openrouter/openai/gpt-5.4-mini / ours | -47.3 | 0.328 | -7.3 (-22.0 to +6.1) |
| openrouter/deepseek/deepseek-v4.1-flash / ours | -45.7 | 0.329 | -5.6 (-27.6 to +17.0) |

A range that crosses zero means the test cannot tell the two apart on this many questions.

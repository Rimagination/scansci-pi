---
name: nature-statistics
description: Statistical reporting and audit for scientific manuscripts, figures, and supplementary materials. Use for p-values, sample size, replicates, effect sizes, confidence intervals, multiple comparisons, model assumptions, or cross-section numerical consistency.
---

# Nature Statistics

Audit the analysis and the reporting separately.

1. Identify the experimental unit, observational unit, sample size, biological and technical replicates, exclusions, missing values, and randomization or blocking.
2. Check that the statistical test matches the design, outcome type, dependence structure, distributional assumptions, and comparison question.
3. Report effect size and uncertainty alongside p-values. State the multiplicity procedure when multiple hypotheses or time points are tested.
4. Trace every number across text, tables, figures, captions, supplement, and abstract. Flag inconsistent denominators, rounding, units, degrees of freedom, and significant-figure precision.
5. Distinguish exploratory, confirmatory, model-based, and descriptive analyses. Do not repair a flawed analysis by silently changing the method.

Return a finding table with location, issue, severity, evidence, recommended wording, and whether reanalysis is required. Do not invent data, test results, or a compliant journal policy; verify venue-specific rules when the target journal is known.

This is a ScanSci adaptation of the `nature-statistics` workflow from Yuan1z0825/nature-skills. R workflows should use the repository-configured Rscript path when execution is explicitly requested.

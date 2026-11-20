---
title: Fabric Capacity Planning
description: Estimate preliminary Fabric capacity from assessed Alteryx Dataflow Gen2 workflows
ms.date: 2026-11-20
ms.topic: how-to
---

## Capacity planning scope

The Capacity Planning tab converts static Alteryx and Informatica (PowerCenter
and IDMC) workflow evidence and analyst-supplied operating inputs into a
preliminary Fabric F-SKU range. The model covers:

* Dataflow Gen2 (calibrated workbook model using Alteryx or Informatica step weights)
* Fabric Notebook (heuristic Spark model using 1 Fabric CU = 2 Spark vCores)
* Fabric Pipeline (heuristic orchestration and copy activity model)
* Mixed Fabric solution (sums the active Dataflow, Notebook, and Pipeline components)
* Manual rework (indicative Dataflow-basis estimate from the reference workbook
  weights while redesign remains required)

Informatica PowerCenter and IDMC mappings use the Informatica step weights
(including Lookups at `0.65`, Aggregators at `0.10`, Sorters at `0.08`,
Unions/Normalizers at `0.12`, Update Strategy at `0.35`, and SQL/Stored
Proc/Java at `0.85`). Thin IDMC `MTT` mapping-task wrappers that reference an
assessed mapping in the same package are excluded from capacity totals to avoid
double-counting.

The application contains a deterministic Python implementation of the
calculator formulas, tool classifications, weights, and scenario logic. It
does not read the reference HTML, workbook, or PDF at runtime.

> [!IMPORTANT]
> Capacity output is a planning estimate. Run representative workflows in
> Fabric and validate measured consumption in the Fabric Capacity Metrics app
> before purchasing or reserving capacity.

## Confirm workflow inputs

1. Complete an assessment.
2. Open **Capacity Planning**.
3. Review each modeled workflow.
4. Set the refresh interval, source rows per run, and optional Spark vCores or
   runtime seconds for Notebook routes.
5. Choose whether Notebook compute is included in the base F-SKU (default) or
   offloaded to **Autoscale Billing for Spark**, and adjust **Interactive
   users** (default `1`, or `0` for ETL-only sizing).
6. Select **Save and recalculate** to accept the current values and update the
   estimate.

The initial values are one run per day, 1,000 source rows per run, and 8 Spark
vCores (4 Fabric CUs) with automatic runtime estimation. The Portfolio and
Capacity Planning views immediately display the assessment-based F-SKU labeled
with **Default assumptions** until you update and save custom operating inputs.

The Dataflow Gen2 formula uses the largest of minimum duration, complexity
duration, and row-volume duration. Rows per run can therefore change without
changing Dataflow capacity when minimum or complexity duration remains larger.
The workflow row identifies the current driver and the approximate volume
threshold where row volume becomes the base-duration driver.

## Interpret scenarios

The page provides three concurrency scenarios:

* Optimized assumes modeled jobs are staggered
* Balance applies the configured midpoint between staggered and overlapping demand
* Peak assumes modeled jobs can start together

Each workflow shows component CU-seconds (`DF`, `NB`, `PL`), total CU-seconds
per run, and monthly CU-hours. The F-SKU is a portfolio result because
workflows share capacity and can overlap. Switching to **Autoscale Billing for
Spark** removes Fabric Notebook demand from the base F-SKU scenarios and reports
Spark CU-hours per month separately.

## Understand exclusions

The capacity model excludes:

* Thin IDMC `MTT` mapping tasks whose referenced mapping is already modeled in the same package
* Pricing, OneLake storage, and network demand

Excluded workflows remain visible with a reason. The modeled coverage
percentage prevents a partial estimate from appearing to represent the entire
portfolio.

## Storage and exports

Mutable capacity inputs and settings are stored in the same local SQLite
database as assessment runs. They remain separate from the immutable
assessment result and are recomputed with the recorded capacity model version.

Use **Export JSON** for the complete estimate and model assumptions. Use
**Export CSV** for workflow inputs, status, exclusions, and CU contributions.

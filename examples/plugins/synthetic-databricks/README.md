---
title: Synthetic Databricks provider example
description: Manual-review-only target plugin for extension contract testing
---

## Synthetic Databricks provider example

This independently packaged example demonstrates target-provider discovery and
evaluation. It always recommends manual review; it does not assess Databricks
semantics, generate code, estimate capacity, or deploy artifacts.

Install it only in an isolated development environment. It replaces the
`databricks` placeholder when discovered and must not be used as a production
provider or installed alongside a real provider with the same platform ID.
Build and install it with the current core package from this checkout; earlier
published core packages may not contain the required contracts.

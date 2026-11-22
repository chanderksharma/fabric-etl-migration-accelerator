---
title: Synthetic SSIS source adapter example
description: Metadata-only SSIS source plugin for extension contract testing
---

## Synthetic SSIS source adapter example

This example accepts only an already staged, single `.dtsx` XML file whose root
is a `DTS:Executable` with `DTS:ExecutableType="SSIS.Package.2"`. The package
and nested executable elements must have `DTS:DTSID` and `DTS:ObjectName`
attributes. It extracts identities only; every package and task is marked for
manual review. It does not interpret connections, expressions, control flow,
data flow, scripts, or deployment behavior.

The adapter rejects DTDs, entities, linked files, files over 5 MiB, and packages
with more than 10,000 executable elements (including the package). It is
for synthetic contract testing, not production SSIS migration. Installing it
allows local-file and ZIP member discovery and neutral assessment through the
local run service, portal, and portfolio library. It does not add Fabric assessment
or generation. Build and install it with the current core package from this checkout.

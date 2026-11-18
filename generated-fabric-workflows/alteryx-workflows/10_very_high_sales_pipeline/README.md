# 10_very_high_sales_pipeline Fabric workflow bundle

Source workflow: `alteryx-workflows\10_very_high_sales_pipeline.yxmd`

Generation status: `native_ready`

> [!IMPORTANT]
> Independent semantic validation remains required. Generated definitions
> can be structurally deployable while source connections, destinations,
> credentials, schemas, and business parity still require configuration.

## Bundle contents

| File | Purpose |
| --- | --- |
| `dataflow-create-item.json` | Fabric REST create-item request for the Dataflow. |
| `dataflow-manifest.json` | Generated candidate status, bindings, and diagnostics. |
| `dataflow-mashup.pq` | Power Query M transformations. |
| `dataflow-queryMetadata.json` | Dataflow queries, groups, loads, and connections. |
| `dataflow.platform.json` | Dataflow Fabric item metadata. |
| `deployment-bundle.json` | Deployment order and item dependencies. |
| `notebook-content.ipynb` | Documented Fabric PySpark notebook. |
| `notebook-create-item.json` | Fabric REST create-item request for the Notebook. |
| `notebook-manifest.json` | Generated candidate status, bindings, and diagnostics. |
| `notebook.platform.json` | Notebook Fabric item metadata. |
| `pipeline-content.json` | Fabric Data Pipeline activity definition. |
| `pipeline-create-item.json` | Fabric REST create-item request for the pipeline. |
| `pipeline-diagnostics.json` | Compiler blockers that require implementation. |
| `pipeline-manifest.json` | Generated candidate status, bindings, and diagnostics. |
| `pipeline.platform.json` | Pipeline Fabric item metadata. |

## Manual deployment

### Prerequisites

- PowerShell 7 and Azure CLI.
- A Microsoft Fabric workspace on active capacity.
- Contributor or higher permission on the target workspace.
- Permission to create the included Fabric item types.
- Approved source connections and destination items.

### Authenticate and select the workspace

```powershell
az login
$WorkspaceId = "<fabric-workspace-guid>"
```

### Configure bindings before deployment

Review the decoded definition files before using the request envelopes.
Dataflow source and destination bindings are intentionally unresolved when
workspace connection IDs cannot be inferred. Notebook `source_paths` values
must be completed before execution. If a decoded definition changes, update
the matching Base64 part in its `*-create-item.json` envelope.

### Create the generated items

Run the following commands from this extracted bundle directory. Create
items in Dataflow, Notebook, then Data Pipeline order when all are present.

```powershell
# Create the item described by dataflow-create-item.json
az rest --method post `
  --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces/$WorkspaceId/items" `
  --headers "Content-Type=application/json" `
  --body "@dataflow-create-item.json"

# Create the item described by notebook-create-item.json
az rest --method post `
  --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces/$WorkspaceId/items" `
  --headers "Content-Type=application/json" `
  --body "@notebook-create-item.json"

# Create the item described by pipeline-create-item.json
az rest --method post `
  --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces/$WorkspaceId/items" `
  --headers "Content-Type=application/json" `
  --body "@pipeline-create-item.json"

```
### Pipeline dependency IDs

Deploy the Dataflow and Notebook first. Capture the returned item IDs, replace
`{{WORKSPACE_ID}}`, `{{DATAFLOW_ITEM_ID}}`, `{{NOTEBOOK_ITEM_ID}}` in
`pipeline-content.json`, then rebuild the `pipeline-content.json` Base64 payload
inside `pipeline-create-item.json` before creating the pipeline.

## Post-deployment verification

1. Open each created item in the Fabric workspace.
2. Configure and test source connections and destination bindings.
3. Run source previews before the first full execution.
4. Compare schemas, row counts, null behavior, and business calculations
   with the Alteryx workflow.
5. Promote only after independent parity and operational validation.

## Compiler diagnostics

- No compiler diagnostics were recorded.

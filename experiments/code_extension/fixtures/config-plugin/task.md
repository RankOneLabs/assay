# Config plugin candidate — blocked before fixture extraction

Status: **not frozen or qualified**. This preserves the requested public contract for review; it must not be offered to an agent or included in a pilot manifest.

Add a stage compiler plugin loaded from an existing stage-plugin configuration. The loader must discover only configured available plugins, validate the plugin's configuration, use existing defaults when no plugin is configured, and leave `delegated_session` and `provision_repository_refs` behavior unchanged. A plugin present in source but omitted from configuration must not load. Public checks would be `bun test ./tests/visible` and `tsc --noEmit -p tsconfig.json`; submission would use `submit_output`. The plugin API and configuration key cannot be specified faithfully until a source slice containing the loading path is selected.

The pinned slice has `compileWorkflowDefinition(definition, registry?: StageTypeCompilerRegistry)` and a built-in registry, but no stage-plugin configuration or loader. Exact configuration key, loader API, writable configuration path, and protected configuration files therefore cannot be frozen without inventing a production loading path.

## Requirements to intended hidden assertions

| Intended assertion | Public requirement or prior behavior | Status in pinned slice |
| --- | --- | --- |
| Discovery and loading | Load the added plugin through existing configuration. | No configuration-driven loading path exists. |
| Configuration validation | Reject invalid configured plugin values. | No plugin configuration schema exists. |
| Default behavior | An absent plugin config uses existing defaults; an unconfigured plugin is not loaded. | Only the built-in registry default exists. |
| Existing plugins | `delegated_session` and `provision_repository_refs` remain unchanged. | Both built-in compilers exist. |

No hidden tests or patches have been authored for this blocked candidate.

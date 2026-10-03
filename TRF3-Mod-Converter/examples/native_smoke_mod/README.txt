Own, harmless native TF3 script fixture with legacy res/ layout.
Convert this folder to a separate output before installing it.
The converter must preserve its modId, callback params and helper reference,
and move res/ to content/. Renaming this modId must be refused until all
internal references are migrated explicitly.

Enable only on a separate test map. Expected stdout markers:
TF3_MAPSTUDIO_CONVERTER_030_RUN_OK mode=1 helper=helper_ok config=table
TF3_MAPSTUDIO_CONVERTER_030_POST_OK mode=1 helper=helper_ok
TF3_MAPSTUDIO_CONVERTER_030_PRE_OBSERVED records whether preRun is invoked.

Lifecycle callbacks receive configDict/allModParams, not resource captureParams.
Their nested reference params are retained by export but are not used by this
test. Top-level mod.params (numbers=[7.0]) tests actual mod parameter dispatch.
Build 40408 Map Editor supplied the selected option index 1 rather than 7;
the converter preserves the metadata and does not silently rewrite scripts.

This fixture validates metadata/layout conversion and callback dispatch.
It does not demonstrate automatic conversion of TF2 gameplay APIs or assets.

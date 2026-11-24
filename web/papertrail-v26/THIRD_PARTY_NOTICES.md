# Annotation workbench dependencies and adaptations

This version extends the existing local Papertrail app without rewriting sealed algorithms or the original UI. Preact 11.1.0 (MIT), HTM 3.1.1 (Apache-2.0), Lucide 1.8.0 (ISC with inherited attribution), and their complete licenses are retained unmodified under dist/vendor.

The annotation form actually instantiates **@json-editor/json-editor 2.17.3** (MIT). The official npm archive is verified with its published SHA512; selected prebuilt files are copied without running prepare/build/install scripts. The library owns schema field rendering, enum selection, setValue/getValue and validation. Project code supplies field schemas, synchronizes unblurred input before saving, and adapts workflow, revision and ownership persistence. It is not a copied or renamed annotation framework.

Full JSON Editor MIT license and the archive's extracted license notices are included. The prebuilt distribution embeds core-js 3.36.1 and regenerator runtime. CORE_JS_LICENSE and REGENERATOR_LICENSE preserve their complete upstream MIT terms and copyright notices; no extra runtime packages were installed.

Compared upstream projects before selection:

| Project | Inspected license/state | Adaptation decision |
|---|---|---|
| HumanSignal/label-studio | Repository root Apache-2.0, editor package declares MIT; active/nonarchived, pushed 2026-10-28 | Read native Choices and editor dependencies. Full React/MobX/editor stack adds integration cost. Not installed or copied; native data/annotations/result export shape retained for interoperability. |
| doccano/doccano | MIT, nonarchived, pushed 2026-04-14 | Read README startup/service requirements. A separate annotation server/task worker is unnecessary for nine local requests. Not installed or copied. |
| json-editor/json-editor | MIT, active/nonarchived, pushed 2026-10-12 | Selected prebuilt 2.17.3; read SelectEditor, package and licensing, then inspected native StringEditor in the verified archive for input behavior. |

Maintenance observations and source blob identifiers are recorded in reports/stage26/upstream-audit.json, published archive/version/asset hashes in editor-assets.json. License checks and dependency inspection do not constitute a full vulnerability audit.

The pre-existing sklearn 1.9.1/SQLite FTS5 and project QualityRetrieval implement candidate ranking; fixed 0.7 query/0.3 displayed context is inherited, not tuned on judgments. Topic-only requests use a zero reading-context vector. Seen/time filtering remains shared. No new model training, external evaluation data or LLM labels.

Script policy stays same-origin and disallows unsafe-eval. Only the annotation HTML response permits inline styles because JSON Editor writes generated theme and element styles. User-supplied paper/request text is rendered as escaped text; schemas do not accept executable templates, HTML or remote refs.

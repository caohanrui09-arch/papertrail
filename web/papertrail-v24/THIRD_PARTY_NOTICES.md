# Phase 24 reuse and changes

Frontend is an independent version of phase23 Papertrail. Unmodified Preact 11.1.0 (MIT), HTM 3.1.1 (Apache-2.0), and Lucide 1.8.0 (ISC with included attribution) remain in dist/vendor with their complete license files. No new frontend package was installed. Project adaptations add preference controls, explanation details, and human-label coverage status.

Backend directly calls the already pinned scikit-learn 1.9.1 (BSD-3-Clause) installed in the independent stage17 CPU runtime. Original installed licensing remains in its distribution; no upstream algorithm source copied into project code. Native TF-IDF, L2 normalization and linear kernel implement the math. SQLite (Python standard library) supplies transactional persistence; preference/API/UI adapters are project code.

Before implementation, inspected GitHub scikit-learn/scikit-learn (BSD-3-Clause, not archived, push 2026-10-28T13:07:43Z) and recommenders-team/recommenders (MIT, not archived, push 2026-10-26T14:26:54Z), with actual core excerpts in reports/stage24/upstream-audit.json. SAR is still available in frozen demonstration mode, but fitting dense collaborative matrices for each new visitor would add cost and would not resolve absent feedback. Personal mode reuses content vectors instead. No claim that content beats SAR on new human labels.

Reviewed licenses: scikit-learn COPYING blob 3d7ee432c15b685eaa654b6abe8f8e3ea8126a8d; Recommenders LICENSE blob e74b0d177a471724e4c0c48cae0f4ba9c05df64b. No new remote code, executable, model pickle, dependency install or cloud upload. Maintenance/license inspection is not an exhaustive vulnerability audit.

Source links: https://github.com/scikit-learn/scikit-learn/blob/main/COPYING ; https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/metrics/pairwise.py ; https://github.com/recommenders-team/recommenders/blob/main/LICENSE ; https://github.com/recommenders-team/recommenders/blob/main/recommenders/models/sar/sar_singlenode.py . The audit records observed blob hashes; execution continues using the pre-existing pinned runtime, not mutable main.

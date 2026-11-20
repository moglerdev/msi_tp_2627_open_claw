# Datasets

One folder per dataset:

```
<dataset>/
├── inputs/     # source documents (binaries are stored via Git LFS)
├── expected/   # ground truth, same base name as the input (e.g. report.pdf -> report.json)
└── README.md   # source, license, what this dataset tests
```

Only add documents we may redistribute — no personal data, no copyrighted course material.
Run `git lfs install` once per machine before adding PDFs or Office files.

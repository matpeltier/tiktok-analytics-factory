# data/

Raw data lives locally or in object storage — **not in Git**.

## Intended local artifact layout

```text
data/
  raw/                    # immutable raw source material (git-ignored)
    <video_id>/
      video.mp4           # original downloaded video
      metadata.json       # raw public metadata as captured
  models/                 # raw + parsed model responses (git-ignored)
    <video_id>/<run_id>/
      response.raw.txt
      response.parsed.json
      provenance.json
  derived/                # regenerable derived artifacts (git-ignored)
  datasets/               # assembled modeling datasets (git-ignored)
```

Rules:

- Everything under `raw/` is immutable once written.
- Raw model responses and parsed outputs are both retained.
- Derived/dataset artifacts always carry provenance and can be regenerated.
- Only documentation files in `data/` are committed; media and run outputs are ignored
  via `.gitignore`.

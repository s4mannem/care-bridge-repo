"""Render a component's Cloud Run manifest once per environment, plus skaffold.yaml.

Reads deploy/components/<component>/service.yaml, substitutes ${VARS}, and
writes service.<env>.yaml and a skaffold.yaml with one profile per env into
--out. Cloud Deploy's pipeline stage for env X uses profile X.

The container image stays the literal `app`; `gcloud deploy releases create
--images=app=<digest>` swaps it in, so one built image moves through every env.

Stdlib only: it runs in the cloud-sdk image.
"""
import argparse
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--component", required=True)
    p.add_argument("--envs", required=True, help="comma-separated, in pipeline order")
    p.add_argument("--prefix", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--project-number", required=True)
    p.add_argument("--region", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    src = ROOT / "deploy" / "components" / a.component / "service.yaml"
    if not src.exists():
        print(f"render: missing {src.relative_to(ROOT)}", file=sys.stderr)
        return 1
    template = string.Template(src.read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    envs = [e.strip() for e in a.envs.split(",") if e.strip()]
    for env in envs:
        values = {
            "PREFIX": a.prefix,
            "COMPONENT": a.component,
            "ENV": env,
            "SERVICE": f"{a.prefix}-{a.component}-{env}",
            "PROJECT_ID": a.project,
            "PROJECT_NUMBER": a.project_number,
            "REGION": a.region,
            "SERVICE_ACCOUNT": f"{a.prefix}-{a.component}@{a.project}.iam.gserviceaccount.com",
        }
        try:
            rendered = template.substitute(values)
        except KeyError as exc:
            print(f"render: {src.relative_to(ROOT)} uses unknown variable {exc}", file=sys.stderr)
            return 1
        (out / f"service.{env}.yaml").write_text(rendered)

    profiles = "".join(f"  - name: {env}\n    manifests:\n      rawYaml: [service.{env}.yaml]\n" for env in envs)
    (out / "skaffold.yaml").write_text(
        "apiVersion: skaffold/v4beta11\n"
        "kind: Config\n"
        f"metadata:\n  name: {a.prefix}-{a.component}\n"
        f"profiles:\n{profiles}"
        "deploy:\n  cloudrun: {}\n"
    )
    print(f"render: {a.component} -> {', '.join(f'service.{e}.yaml' for e in envs)} in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

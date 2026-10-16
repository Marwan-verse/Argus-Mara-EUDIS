"""Prepare human-label templates or score saved vision output without paid calls."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from argus.satellite_workspace import SatelliteWorkspace
from argus.vision_evaluation import evaluate_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT/'data/satellite')
    parser.add_argument('--manifest', type=Path, default=ROOT/'data/validation/vision-labels.json')
    parser.add_argument('--output', type=Path, default=ROOT/'data/validation/vision-report.json')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--tolerance-m', type=float, default=100)
    args = parser.parse_args()
    workspace = SatelliteWorkspace(args.workspace)
    if args.prepare:
        if args.manifest.exists():
            parser.error('Reference labels already exist; choose another manifest instead of overwriting them')
        cases = []
        for scene in workspace.list_scenes():
            if not (workspace.root/'reviews'/(scene['id']+'.json')).is_file():
                continue
            cases.append({'scene_id': scene['id'], 'image_sha256': scene['image_sha256'],
                          'image_file': str((workspace.scenes/(scene['id']+'.png')).resolve()),
                          'reviewed': False, 'reviewer': None, 'reference_source': 'human',
                          'all_visible_contacts_labeled': False, 'truth': None,
                          'instructions': 'Independently label every visible vessel center as {x: fraction from left, y: fraction from top}. Keep uncertain/unreviewed images unreviewed. Do not copy AI predictions into reference labels.'})
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps({'version': 'vision-evaluation-v1', 'cases': cases}, indent=2), encoding='utf-8')
        print(json.dumps({'prepared_images': len(cases), 'manifest': str(args.manifest)}))
    else:
        result = evaluate_manifest(workspace, json.loads(args.manifest.read_text(encoding='utf-8')), args.tolerance_m)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({key: result[key] for key in ('evaluated_images', 'abstained_images', 'precision', 'pipeline_recall', 'verified_model_recall')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

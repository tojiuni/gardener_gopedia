"""HTTP API smoke for /curation routes."""


def test_curation_batch_and_queue(client):
    tc, ds_id, dq_id = client
    r = tc.post(
        "/curation/batches",
        json={
            "dataset_id": ds_id,
            "proposals": [
                {
                    "dataset_query_id": dq_id,
                    "candidates": [
                        {
                            "target_id": "tid",
                            "target_type": "l3_id",
                            "confidence": 0.5,
                            "model_name": "test-model",
                        }
                    ],
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["id"]

    r2 = tc.get(f"/curation/batches/{batch_id}/queue")
    assert r2.status_code == 200
    assert len(r2.json()) == 1

    r3 = tc.post(
        f"/curation/batches/{batch_id}/decisions",
        json={
            "dataset_query_id": dq_id,
            "action": "set_target",
            "target_id": "final-l3",
            "target_type": "l3_id",
            "reviewer": "api",
        },
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "human_accepted"

    r4 = tc.post(
        f"/curation/batches/{batch_id}/promote",
        json={"new_version": "gold-v1"},
    )
    assert r4.status_code == 200
    assert r4.json()["curation_tier"] == "gold"

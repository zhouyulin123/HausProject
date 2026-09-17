"""主任务独立核验空间保存的归属与竞争写入边界。"""

from concurrent.futures import ThreadPoolExecutor

from app.db.models import DesignTask, UploadedImage
from tests.integration.test_spatial_api import context as _context, request

context = _context


def test_foreign_image_cannot_be_bound_to_owned_space(context):
    client, factory, url, headers, _ = context
    with factory() as db:
        other = DesignTask(status="waiting_input")
        db.add(other)
        db.flush()
        image = UploadedImage(task_id=other.id, file_url="/uploads/foreign.png")
        db.add(image)
        db.commit()
        image_id = image.id
    payload = request()
    payload["document"]["source_image_id"] = image_id
    assert client.put(url, headers=headers, json=payload).status_code == 422
    assert client.get(url, headers=headers).json()["version"] == 0


def test_concurrent_edits_cannot_overwrite_each_other(context):
    client, _, url, headers, _ = context
    assert client.put(url, headers=headers, json=request()).status_code == 200
    requests = [request(1, "edit-a"), request(1, "edit-b")]
    for index, payload in enumerate(requests):
        payload["document"]["rooms"][0]["name"] = f"房间 {index}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda payload: client.put(url, headers=headers, json=payload), requests))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert client.get(url, headers=headers).json() == winner


def test_missing_session_cannot_read_or_create_space(context):
    client, _, url, _, _ = context
    assert client.get(url).status_code in {401, 422}
    assert client.put(url, json=request()).status_code in {401, 422}

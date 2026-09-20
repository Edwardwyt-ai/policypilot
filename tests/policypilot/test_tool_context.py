import json

from policypilot.tool_context import project_tool_result


def test_tool_projection_filters_projects_ranges_and_aggregates():
    payload = {
        "records": [
            {
                "transaction_id": f"tx-{index}",
                "status": "PENDING" if index % 2 else "COMPLETED",
                "amount": index,
                "irrelevant_blob": "x" * 50,
            }
            for index in range(30)
        ]
    }

    result = project_tool_result(
        json.dumps(payload), focus="transaction status", max_fields=12
    )

    assert result.total_fields == 120
    assert result.filtered_fields == 12
    assert result.range_selected
    assert result.aggregation["status_counts"] == {
        "COMPLETED": 15,
        "PENDING": 15,
    }
    assert "irrelevant_blob" not in result.content
    assert "tx-0" in result.content
    assert "tx-29" in result.content

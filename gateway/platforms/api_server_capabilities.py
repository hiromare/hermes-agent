"""Authenticated API capability projection, including verified owner extensions."""
import asyncio


async def capabilities(adapter, request):
    from gateway.platforms import api_server as facade
    runner = getattr(adapter, "gateway_runner", None)
    features = {
        "chat_completions": True, "chat_completions_streaming": True,
        "responses_api": True, "responses_streaming": True, "run_submission": True,
        "runs_idempotency": facade._api_runs._idempotency_capabilities(adapter, store_type=facade.RunIdempotencyStore),
        **facade._STATIC_FEATURE_FLAGS,
        "run_unknown_resolution": getattr(runner, "session_authority", None) is not None,
        "cors": bool(adapter._cors_origins)}
    from gateway.platforms.api_server_passive_history import capability_descriptor
    passive = await asyncio.to_thread(capability_descriptor, adapter)
    if passive:
        features.update({key: value for key, value in passive.items() if key != "store_id"})
    return facade.web.json_response({
        **({"store_id": passive["store_id"]} if passive else {}),
        "object": "hermes.api_server.capabilities", "platform": "hermes-agent",
        "model": adapter._model_name,
        "auth": {"type": "bearer", "required": bool(adapter._api_key)},
        "runtime": {
            "mode": "server_agent", "tool_execution": "server", "split_runtime": False,
            "description": (
                "The API server creates a server-side Hermes AIAgent; "
                "tools execute on the API-server host unless a future "
                "explicit split-runtime mode is enabled.")},
        "features": features,
        "endpoints": {
            name: {"method": entry[0], "path": entry[1]}
            for name, entry in facade._CAPABILITY_ENDPOINTS
            if len(entry) < 3 or features[entry[2]]},
    })

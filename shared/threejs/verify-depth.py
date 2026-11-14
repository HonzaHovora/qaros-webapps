"""Read back the shipped depth shader in a live Web App Source's WebGL2 context.

Talks to the Visualizer MCP (`POST /mcp`, JSON-RPC `tools/call` of `devtools_send`), which needs
the MCP endpoint enabled and the Visualizer in Developer UI mode.
"""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request


def call_tool(port, name, arguments):
    """Calls one Visualizer MCP tool and returns its structured answer."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        answer = json.load(response)
    if "error" in answer:
        raise RuntimeError(f"MCP {name} failed: {answer['error']}")
    result = answer["result"]
    if result.get("isError") or result.get("structuredContent") is None:
        texts = [item.get("text", "") for item in result.get("content", [])]
        raise RuntimeError(f"MCP {name} failed: {' '.join(texts)}")
    return result["structuredContent"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    # The Visualizer binds QAR_MCP_SERVER_PORT, else QAR_VIZ_AUTOMATION_PORT, else 17872.
    env_port = os.environ.get("QAR_MCP_SERVER_PORT") or os.environ.get("QAR_VIZ_AUTOMATION_PORT", "")
    parser.add_argument("--port", type=int, default=int(env_port) if env_port.isdigit() else 17872)
    options = parser.parse_args()
    source = Path(__file__).with_name("threejs-render-frame.js").read_text()
    vertex = re.search(r"const fullScreenVertex = `([^`]+)`;", source).group(1)
    fragment = re.search(r"const packFragment = `([^`]+)`;", source).group(1)
    expression = r"""(() => {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 1;
        const gl = canvas.getContext('webgl2');
        if (!gl) throw Error('WebGL2 unavailable');
        const shader = (type, source) => {
            const object = gl.createShader(type);
            gl.shaderSource(object, source); gl.compileShader(object);
            if (!gl.getShaderParameter(object, gl.COMPILE_STATUS))
                throw Error(gl.getShaderInfoLog(object));
            return object;
        };
        try {
            const program = gl.createProgram();
            gl.attachShader(program, shader(gl.VERTEX_SHADER, __VERTEX__));
            gl.attachShader(program, shader(gl.FRAGMENT_SHADER, __FRAGMENT__));
            gl.linkProgram(program);
            if (!gl.getProgramParameter(program, gl.LINK_STATUS))
                throw Error(gl.getProgramInfoLog(program));
            gl.useProgram(program);
            const texture = gl.createTexture();
            gl.bindTexture(gl.TEXTURE_2D, texture);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
            gl.uniform1i(gl.getUniformLocation(program, 'depthTexture'), 0);
            gl.uniform2i(gl.getUniformLocation(program, 'depthOrigin'), 0, 0);
            gl.uniform2f(gl.getUniformLocation(program, 'depthSize'), 1, 1);
            gl.uniform2i(gl.getUniformLocation(program, 'destinationOrigin'), 0, 0);
            gl.uniform1f(gl.getUniformLocation(program, 'halfWidth'), 1);
            gl.uniform1f(gl.getUniformLocation(program, 'tileHeight'), 1);
            return [0, 0.5, 1].map(depth => {
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, 1, 1, 0,
                    gl.RED, gl.FLOAT, new Float32Array([depth]));
                gl.drawArrays(gl.TRIANGLES, 0, 3);
                const bytes = new Uint8Array(4);
                gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
                return Array.from(bytes);
            });
        } finally {
            gl.getExtension('WEBGL_lose_context')?.loseContext();
        }
    })()""".replace("__VERTEX__", json.dumps(vertex)).replace("__FRAGMENT__", json.dumps(fragment))
    result = call_tool(options.port, "devtools_send", {
        "instance_id": options.instance,
        "method": "Runtime.evaluate",
        "params": {"expression": expression, "returnByValue": True},
    })
    payload = result.get("payload", {})
    if not result.get("success") or "exceptionDetails" in payload:
        raise RuntimeError(f"GPU depth check failed: {result}")
    actual = payload.get("result", {}).get("value")
    expected = [[0, 0, 0, 255], [0, 0, 128, 255], [255, 255, 255, 255]]
    if actual != expected:
        raise AssertionError(f"near/mid/far depth bytes: expected {expected}, got {actual}")
    print(f"near/mid/far depth packing OK: {actual}")


if __name__ == "__main__":
    main()

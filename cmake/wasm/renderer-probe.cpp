#include "Context.h"
#include "resource/ResourceManager.h"
#include "resource/ResourceType.h"
#include "graphic/Fast3D/backends/gfx_opengl.h"
#include <SDL.h>
#include <emscripten.h>
#include <nlohmann/json.hpp>
#include <array>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <string>

using nlohmann::json;
// This diagnostic initializes no Ship::Window. Retain its context while the
// browser runtime remains alive; full window teardown is a separate lifecycle test.
static std::shared_ptr<Ship::Context> context;

static void require(bool value, const std::string& message) {
    if (!value) throw std::runtime_error(message);
}

static void glCheck(const char* phase) {
    const auto error = glGetError();
    require(error == GL_NO_ERROR, std::string(phase) + ": GL error " + std::to_string(error));
}

static std::array<int, 4> pixel(int x, int y) {
    unsigned char data[4] = {};
    glFinish();
    glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, data);
    glCheck("readback");
    return {data[0], data[1], data[2], data[3]};
}

static void expectPixel(json& checks, const char* name, int x, int y, std::array<int, 4> expected) {
    auto actual = pixel(x, y);
    for (int i = 0; i < 4; ++i) require(std::abs(actual[i] - expected[i]) <= 1, std::string(name) + ": pixel mismatch");
    checks.push_back({{"name", name}, {"pixel", actual}, {"expected", expected}});
}

static void linked(Fast::ShaderProgram* shader, int stride) {
    require(shader != nullptr && shader->numFloats == stride, "Unexpected generated vertex layout");
    GLint success = GL_FALSE;
    glGetProgramiv(shader->openglProgramId, GL_LINK_STATUS, &success);
    require(success == GL_TRUE, "Generated program did not link");
    glCheck("generated shader");
}

static void solid(Fast::GfxRenderingAPIOGL& renderer, float r, float g, float b) {
    float vertices[] = {-1,-1,0,1,r,g,b,1, 3,-1,0,1,r,g,b,1, -1,3,0,1,r,g,b,1};
    renderer.DrawTriangles(vertices, std::size(vertices), 1);
    glCheck("solid draw");
}

static void publish(const json& result) {
    const std::string text = result.dump();
    EM_ASM({
        window.STARSHIP_WEBGL_RESULT = JSON.parse(UTF8ToString($0));
        if (window.STARSHIP_WEBGL_RESULT.status === 'pass') {
            const gl = Module.canvas.getContext('webgl2');
            window.STARSHIP_WEBGL_RESULT.webglVersion = gl.getParameter(gl.VERSION);
        }
        document.getElementById('result').textContent = JSON.stringify(window.STARSHIP_WEBGL_RESULT, null, 2);
    }, text.c_str());
}

int main() {
    try {
        require(SDL_Init(SDL_INIT_VIDEO) == 0, SDL_GetError());
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_ES);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 0);
        SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24);
        SDL_GL_SetAttribute(SDL_GL_STENCIL_SIZE, 8);
        auto* window = SDL_CreateWindow("Renderer probe", 0, 0, 64, 64, SDL_WINDOW_OPENGL | SDL_WINDOW_SHOWN);
        require(window != nullptr, SDL_GetError());
        const auto glContext = SDL_GL_CreateContext(window);
        require(glContext != nullptr, SDL_GetError());
        require(SDL_GL_MakeCurrent(window, glContext) == 0, SDL_GetError());
        const char* version = reinterpret_cast<const char*>(glGetString(GL_VERSION));
        require(version != nullptr && std::string(version).find("OpenGL ES 3") != std::string::npos,
                "A GLES 3 / WebGL 2 context is required");
        glCheck("context");

        context = Ship::Context::CreateUninitializedInstance("RendererProbe", "renderer-probe", "probe.json");
        require(context->InitConfiguration() && context->InitConsoleVariables(), "Context setup failed");
        require(context->InitResourceManager({"/renderer-assets.zip"}, {}, 1000000), "Shader archive did not load");
        for (const auto* path : {"shaders/opengl/default.shader.vs", "shaders/opengl/default.shader.fs"}) {
            auto init = std::make_shared<Ship::ResourceInitData>();
            init->Type = static_cast<uint32_t>(Ship::ResourceType::Shader);
            init->Format = RESOURCE_FORMAT_BINARY;
            init->ByteOrder = Ship::Endianness::Native;
            init->ResourceVersion = 0;
            require(context->GetResourceManager()->LoadResourceProcess(path, true, init) != nullptr,
                    std::string("Shader warmup failed: ") + path);
        }

        Fast::GfxRenderingAPIOGL renderer{};
        renderer.Init();
        renderer.UpdateFramebufferParameters(0, 64, 64, 1, false, true, true, false);
        renderer.StartDrawToFramebuffer(0, 1);
        renderer.SetViewport(0, 0, 64, 64);
        renderer.SetScissor(0, 0, 64, 64);
        renderer.SetDepthTestAndMask(false, false);
        renderer.SetUseAlpha(false);
        renderer.ClearFramebuffer(true, true);
        glCheck("renderer init");

        json checks = json::array();
        const uint64_t solidId = (uint64_t(SHADER_INPUT_1) << 12) | (uint64_t(SHADER_INPUT_1) << 28);
        auto* solidShader = renderer.CreateAndLoadNewShader(solidId, SHADER_OPT(ALPHA));
        linked(solidShader, 8);
        renderer.SetScissor(0, 0, 32, 64);
        solid(renderer, 1, 0, 0);
        expectPixel(checks, "solid RGBA", 16, 32, {255, 0, 0, 255});

        renderer.UnloadShader(solidShader);
        auto texture = renderer.NewTexture();
        renderer.SelectTexture(0, texture);
        const uint8_t green[] = {0,255,0,255, 0,255,0,255, 0,255,0,255, 0,255,0,255};
        renderer.UploadTexture(green, 2, 2);
        renderer.SetSamplerParameters(0, false, G_TX_CLAMP, G_TX_CLAMP);
        const uint64_t textureId = (uint64_t(SHADER_TEXEL0) << 12) | (uint64_t(SHADER_TEXEL0) << 28);
        auto* textureShader = renderer.CreateAndLoadNewShader(textureId, SHADER_OPT(ALPHA));
        linked(textureShader, 6);
        renderer.SetScissor(32, 0, 32, 64);
        float textured[] = {-1,-1,0,1,.5f,.5f, 3,-1,0,1,.5f,.5f, -1,3,0,1,.5f,.5f};
        renderer.DrawTriangles(textured, std::size(textured), 1);
        glCheck("textured draw");
        expectPixel(checks, "textured RGBA", 48, 32, {0, 255, 0, 255});

        renderer.UnloadShader(textureShader);
        renderer.LoadShader(solidShader);
        auto framebuffer = renderer.CreateFramebuffer();
        renderer.UpdateFramebufferParameters(framebuffer, 16, 16, 1, false, true, true, false);
        renderer.StartDrawToFramebuffer(framebuffer, 1);
        require(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE, "Incomplete framebuffer");
        renderer.SetViewport(0, 0, 16, 16);
        renderer.SetScissor(0, 0, 16, 16);
        renderer.ClearFramebuffer(true, true);
        solid(renderer, 0, 0, 1);
        expectPixel(checks, "offscreen framebuffer", 8, 8, {0, 0, 255, 255});
        renderer.StartDrawToFramebuffer(0, 1);
        renderer.SetViewport(0, 0, 64, 64);
        renderer.SetScissor(0, 0, 64, 64);
        renderer.EndFrame();
        SDL_GL_SwapWindow(window);
        glCheck("presentation");

        publish({{"status", "pass"}, {"glesVersion", version},
                 {"renderer", reinterpret_cast<const char*>(glGetString(GL_RENDERER))},
                 {"checks", checks}, {"shaderPrograms", 2}, {"glError", 0},
                 {"scope", "actual libultraship GLES renderer; not a game boot"}});
        return 0;
    } catch (const std::exception& error) {
        publish({{"status", "fail"}, {"error", error.what()}});
        return 1;
    }
}

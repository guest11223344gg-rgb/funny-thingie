// Minimal GLES3 + Emscripten smoke test.
// Exists to prove the toolchain, not to be useful. Delete once Torque3D
// renders under Emscripten.
#include <GLES3/gl3.h>
#include <emscripten.h>
#include <emscripten/html5.h>
#include <cstdio>
#include <cstdint>

static GLuint g_program = 0;

static const char* kVertexShader =
    "#version 300 es\n"
    "layout(location=0) in vec2 position;\n"
    "out vec2 uv;\n"
    "void main() {\n"
    "    uv = position * 0.5 + 0.5;\n"
    "    gl_Position = vec4(position, 0.0, 1.0);\n"
    "}\n";

static const char* kFragmentShader =
    "#version 300 es\n"
    "precision highp float;\n"
    "in vec2 uv;\n"
    "out vec4 fragColor;\n"
    "void main() {\n"
    // Deliberately asymmetric so a black or blank frame is distinguishable
    // from a correctly rendered one.
    "    fragColor = vec4(uv.x, uv.y, 0.25, 1.0);\n"
    "}\n";

static GLuint compile(GLenum type, const char* source) {
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint ok = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(shader, sizeof(log), nullptr, log);
        printf("shader compile failed: %s\n", log);
    }
    return shader;
}

static void init() {
    printf("GL_VERSION  = %s\n", glGetString(GL_VERSION));
    printf("GL_RENDERER = %s\n", glGetString(GL_RENDERER));

    GLuint vs = compile(GL_VERTEX_SHADER, kVertexShader);
    GLuint fs = compile(GL_FRAGMENT_SHADER, kFragmentShader);

    g_program = glCreateProgram();
    glAttachShader(g_program, vs);
    glAttachShader(g_program, fs);
    glLinkProgram(g_program);

    GLint linked = GL_FALSE;
    glGetProgramiv(g_program, GL_LINK_STATUS, &linked);
    if (!linked) {
        char log[1024];
        glGetProgramInfoLog(g_program, sizeof(log), nullptr, log);
        printf("program link failed: %s\n", log);
    }
    glDeleteShader(vs);
    glDeleteShader(fs);

    // One triangle covering roughly the whole viewport.
    static const float verts[] = {-1.0f, -1.0f, 3.0f, -1.0f, -1.0f, 3.0f};
    GLuint vbo = 0;
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);

    printf("smoke init complete\n");
    EM_ASM({ window.__smokeReady = true; });
}

static void frame() {
    int w = 0, h = 0;
    emscripten_get_canvas_element_size("#canvas", &w, &h);
    glViewport(0, 0, w, h);
    glClearColor(0.05f, 0.05f, 0.08f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(g_program);
    glDrawArrays(GL_TRIANGLES, 0, 3);
}

// --- threading probe -------------------------------------------------------
// Writes a value to a shared buffer from a worker thread and reads it back on
// the main thread. This is the exact mechanism the vehicle simulation will use
// to publish transforms, reduced to its smallest testable form.
#include <atomic>
#include <thread>
#include <chrono>

static std::atomic<int> g_threadResult{0};

static void threadProbe() {
    std::thread worker([] {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        g_threadResult.store(4242, std::memory_order_release);
    });
    worker.join();  // joining forces the pthread machinery to be real
}

static void checkThreadProbe() {
    if (g_threadResult.load(std::memory_order_acquire) == 4242) {
        printf("thread roundtrip ok\n");
        EM_ASM({ window.__threadTestDone = true; });
    } else {
        printf("thread roundtrip FAILED\n");
        EM_ASM({ window.__threadTestDone = true; });
    }
}

int main() {
    // Ask for GLES3 explicitly; the default is GLES2, which cannot compile
    // the "#version 300 es" shaders above.
    EmscriptenWebGLContextAttributes attrs;
    emscripten_webgl_init_context_attributes(&attrs);
    attrs.majorVersion = 2;   // WebGL2
    attrs.minorVersion = 0;
    attrs.alpha = false;
    attrs.depth = true;
    attrs.antialias = false;

    EMSCRIPTEN_WEBGL_CONTEXT_HANDLE ctx =
        emscripten_webgl_create_context("#canvas", &attrs);
    if (ctx <= 0) {
        printf("failed to create WebGL2 context (%d)\n", (int)ctx);
        return 1;
    }
    emscripten_webgl_make_context_current(ctx);

    init();
    threadProbe();
    checkThreadProbe();
    emscripten_set_main_loop(frame, 0, 0);
    return 0;
}

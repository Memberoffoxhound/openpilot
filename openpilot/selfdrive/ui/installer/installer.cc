#include <algorithm>
#include <array>
#include <cassert>
#include <cctype>
#include <deque>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#include "common/swaglog.h"
#include "common/util.h"
#include "common/hardware/hw.h"
#include "raylib.h"

int freshClone();
int cachedFetch(const std::string &cache);
int executeGitCommand(const std::string &cmd);

std::string get_str(std::string const s) {
  std::string::size_type pos = s.find('?');
  assert(pos != std::string::npos);
  return s.substr(0, pos);
}

// Leave some extra space for the fork installer
const std::string GIT_URL = get_str("https://github.com/commaai/openpilot.git" "?                                                                ");
const std::string BRANCH_STR = get_str(BRANCH "?                                                                ");

#define GIT_SSH_URL "git@github.com:commaai/openpilot.git"
#define CONTINUE_PATH "/data/continue.sh"
#define INSTALLER_MODE_PATH "/tmp/installer_mode"

const std::string INSTALL_PATH = "/data/openpilot";
const std::string VALID_CACHE_PATH = "/data/.openpilot_cache";

#define TMP_INSTALL_PATH "/data/tmppilot"

const int FONT_SIZE = 160;

extern const uint8_t str_continue[] asm("_binary_selfdrive_ui_installer_continue_openpilot_sh_start");
extern const uint8_t str_continue_end[] asm("_binary_selfdrive_ui_installer_continue_openpilot_sh_end");
extern const uint8_t inter_ttf[] asm("_binary_selfdrive_ui_installer_inter_ascii_ttf_start");
extern const uint8_t inter_ttf_end[] asm("_binary_selfdrive_ui_installer_inter_ascii_ttf_end");
extern const uint8_t inter_light_ttf[] asm("_binary_selfdrive_assets_fonts_Inter_Light_ttf_start");
extern const uint8_t inter_light_ttf_end[] asm("_binary_selfdrive_assets_fonts_Inter_Light_ttf_end");
extern const uint8_t inter_bold_ttf[] asm("_binary_selfdrive_assets_fonts_Inter_Bold_ttf_start");
extern const uint8_t inter_bold_ttf_end[] asm("_binary_selfdrive_assets_fonts_Inter_Bold_ttf_end");

Font font_inter;
Font font_roman;
Font font_display;

const bool tici_device = Hardware::get_device_type() == cereal::InitData::DeviceType::TICI ||
                         Hardware::get_device_type() == cereal::InitData::DeviceType::TIZI;

std::vector<std::string> tici_prebuilt_branches = {"release3", "release-tici", "release3-staging", "nightly", "nightly-dev"};
std::string migrated_branch;

bool g_verbose = false;
int g_progress = 0;
std::string g_status;
std::deque<std::string> g_log;

void branchMigration() {
  migrated_branch = BRANCH_STR;
  cereal::InitData::DeviceType device_type = Hardware::get_device_type();
  if (device_type == cereal::InitData::DeviceType::TICI) {
    if (std::find(tici_prebuilt_branches.begin(), tici_prebuilt_branches.end(), BRANCH_STR) != tici_prebuilt_branches.end()) {
      migrated_branch = "release-tici";
    } else if (BRANCH_STR == "master") {
      migrated_branch = "master-tici";
    }
  } else if (device_type == cereal::InitData::DeviceType::TIZI) {
    if (BRANCH_STR == "release3") {
      migrated_branch = "release-tizi";
    } else if (BRANCH_STR == "release3-staging") {
      migrated_branch = "release-tizi-staging";
    }
  } else if (device_type == cereal::InitData::DeviceType::MICI) {
    if (BRANCH_STR == "release3") {
      migrated_branch = "release-mici";
    } else if (BRANCH_STR == "release3-staging") {
      migrated_branch = "release-mici-staging";
    }
  }
}

void run(const char* cmd) {
  int err = std::system(cmd);
  assert(err == 0);
}

std::string trimCopy(std::string s) {
  s.erase(std::remove(s.begin(), s.end(), '\r'), s.end());
  s.erase(std::remove(s.begin(), s.end(), '\n'), s.end());
  while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) {
    s.pop_back();
  }
  size_t i = 0;
  while (i < s.size() && std::isspace(static_cast<unsigned char>(s[i]))) {
    i++;
  }
  return s.substr(i);
}

std::string ellipsize(const std::string &s, size_t max_chars) {
  if (s.size() <= max_chars) {
    return s;
  }
  if (max_chars < 2) {
    return s.substr(0, max_chars);
  }
  return s.substr(0, max_chars - 1) + ".";
}

void writeInstallerMode(bool verbose) {
  std::ofstream f(INSTALLER_MODE_PATH);
  if (f) {
    f << (verbose ? "verbose" : "simple") << "\n";
  }
}

void setStatus(const std::string &status) {
  g_status = status;
}

void pushLog(const std::string &line) {
  std::string cleaned = trimCopy(line);
  if (cleaned.empty()) {
    return;
  }
  if (!g_log.empty() && g_log.back() == cleaned) {
    return;
  }
  g_log.push_back(cleaned);
  while (g_log.size() > 5) {
    g_log.pop_front();
  }
}

Color white90() {
  return (Color){255, 255, 255, (unsigned char)(255 * 0.9)};
}

Color white65() {
  return (Color){255, 255, 255, (unsigned char)(255 * 0.9 * 0.65)};
}

void renderSimpleProgress(int progress) {
  if (tici_device) {
    DrawTextEx(font_inter, "Installing...", (Vector2){150, 290}, 110, 0, WHITE);
    Rectangle bar = {150, 570, (float)GetScreenWidth() - 300, 72};
    DrawRectangleRec(bar, (Color){41, 41, 41, 255});
    progress = std::clamp(progress, 0, 100);
    bar.width *= progress / 100.0f;
    DrawRectangleRec(bar, (Color){70, 91, 234, 255});
    DrawTextEx(font_inter, (std::to_string(progress) + "%").c_str(), (Vector2){150, 670}, 85, 0, WHITE);
  } else {
    DrawTextEx(font_display, "installing...", (Vector2){12, 0}, 77, 0, white90());
    const std::string percent_str = std::to_string(progress) + "%";
    DrawTextEx(font_inter, percent_str.c_str(), (Vector2){12, (float)(GetScreenHeight() - 154 + 20)}, 154, 0, white65());
  }
}

void renderVerboseProgress(int progress) {
  progress = std::clamp(progress, 0, 100);
  const std::string percent_str = std::to_string(progress) + "%";
  const std::string status = g_status.empty() ? (tici_device ? "Working" : "working") : g_status;

  if (tici_device) {
    DrawTextEx(font_display, "Installing...", (Vector2){150, 160}, 90, 0, WHITE);
    DrawTextEx(font_inter, status.c_str(), (Vector2){150, 280}, 56, 0, white90());

    Rectangle bar = {150, 380, (float)GetScreenWidth() - 300, 56};
    DrawRectangleRec(bar, (Color){41, 41, 41, 255});
    Rectangle fill = bar;
    fill.width *= progress / 100.0f;
    DrawRectangleRec(fill, (Color){70, 91, 234, 255});
    DrawTextEx(font_inter, percent_str.c_str(), (Vector2){150, 460}, 70, 0, WHITE);

    float y = 560;
    const int log_size = 36;
    const size_t max_chars = 70;
    for (const auto &line : g_log) {
      DrawTextEx(font_roman, ellipsize(line, max_chars).c_str(), (Vector2){150, y}, log_size, 0, white65());
      y += 48;
    }
  } else {
    // comma 4 is 536x240. Keep type large enough to read at arm's length.
    DrawTextEx(font_display, "installing...", (Vector2){12, 2}, 32, 0, white90());
    DrawTextEx(font_inter, ellipsize(status, 28).c_str(), (Vector2){12, 36}, 22, 0, white65());

    Rectangle bar = {12, 64, (float)GetScreenWidth() - 24, 10};
    DrawRectangleRec(bar, (Color){41, 41, 41, 255});
    Rectangle fill = bar;
    fill.width *= progress / 100.0f;
    DrawRectangleRec(fill, (Color){70, 91, 234, 255});

    DrawTextEx(font_inter, percent_str.c_str(), (Vector2){12, 78}, 40, 0, white90());

    float y = 124;
    const int log_size = 16;
    const size_t max_chars = 42;
    for (const auto &line : g_log) {
      DrawTextEx(font_roman, ellipsize(line, max_chars).c_str(), (Vector2){12, y}, log_size, 0, white65());
      y += 18;
    }
  }
}

void renderProgress(int progress) {
  g_progress = progress;
  BeginDrawing();
    ClearBackground(BLACK);
    if (g_verbose) {
      renderVerboseProgress(progress);
    } else {
      renderSimpleProgress(progress);
    }
  EndDrawing();
}

void finishInstall() {
  BeginDrawing();
    ClearBackground(BLACK);
    if (tici_device) {
      const char *m = "Finishing install...";
      int text_width = MeasureText(m, FONT_SIZE);
      DrawTextEx(font_display, m, (Vector2){(float)(GetScreenWidth() - text_width)/2 + FONT_SIZE, (float)(GetScreenHeight() - FONT_SIZE)/2}, FONT_SIZE, 0, WHITE);
    } else {
      DrawTextEx(font_display, "finishing setup", (Vector2){12, 0}, 77, 0, white90());
    }
  EndDrawing();
  util::sleep_for(60 * 1000);
}

void drawModeButton(Rectangle rec, const char *title, const char *subtitle, bool pressed) {
  Color fill = pressed ? (Color){70, 91, 234, 255} : (Color){41, 41, 41, 255};
  DrawRectangleRounded(rec, 0.12f, 8, fill);
  if (tici_device) {
    DrawTextEx(font_display, title, (Vector2){rec.x + 40, rec.y + rec.height / 2 - 70}, 64, 0, WHITE);
    DrawTextEx(font_inter, subtitle, (Vector2){rec.x + 40, rec.y + rec.height / 2 + 8}, 40, 0, white65());
  } else {
    DrawTextEx(font_display, title, (Vector2){rec.x + 16, rec.y + 14}, 28, 0, WHITE);
    DrawTextEx(font_inter, subtitle, (Vector2){rec.x + 16, rec.y + 48}, 18, 0, white65());
  }
}

bool loadInstallerModeFromDisk() {
  std::ifstream f(INSTALLER_MODE_PATH);
  if (!f) {
    return false;
  }
  std::string mode;
  f >> mode;
  if (mode == "verbose") {
    g_verbose = true;
    return true;
  }
  if (mode == "simple") {
    g_verbose = false;
    return true;
  }
  return false;
}

void promptInstallMode() {
  if (loadInstallerModeFromDisk()) {
    return;
  }

  SetTargetFPS(30);
  while (!WindowShouldClose()) {
    const int w = GetScreenWidth();
    const int h = GetScreenHeight();
    Rectangle simple_rec;
    Rectangle verbose_rec;

    if (tici_device) {
      float btn_w = (w - 150 * 2 - 40) / 2.0f;
      float btn_h = 280;
      float y = 420;
      simple_rec = {150, y, btn_w, btn_h};
      verbose_rec = {150 + btn_w + 40, y, btn_w, btn_h};
    } else {
      float btn_w = w - 24;
      float btn_h = 78;
      simple_rec = {12, 56, btn_w, btn_h};
      verbose_rec = {12, 144, btn_w, btn_h};
    }

    Vector2 pos = GetMousePosition();
    bool tap = IsMouseButtonReleased(MOUSE_BUTTON_LEFT);
    bool simple_hot = CheckCollisionPointRec(pos, simple_rec);
    bool verbose_hot = CheckCollisionPointRec(pos, verbose_rec);

    BeginDrawing();
      ClearBackground(BLACK);
      if (tici_device) {
        DrawTextEx(font_display, "Choose install mode", (Vector2){150, 200}, 90, 0, WHITE);
        DrawTextEx(font_inter, "Simple shows percent. Verbose shows each step.",
                   (Vector2){150, 310}, 40, 0, white65());
      } else {
        DrawTextEx(font_display, "install mode", (Vector2){12, 8}, 32, 0, white90());
      }
      drawModeButton(simple_rec, tici_device ? "Simple" : "simple",
                     tici_device ? "Percent only" : "percent only", simple_hot && IsMouseButtonDown(MOUSE_BUTTON_LEFT));
      drawModeButton(verbose_rec, tici_device ? "Verbose" : "verbose",
                     tici_device ? "Show each step" : "show each step", verbose_hot && IsMouseButtonDown(MOUSE_BUTTON_LEFT));
    EndDrawing();

    if (tap && simple_hot) {
      g_verbose = false;
      break;
    }
    if (tap && verbose_hot) {
      g_verbose = true;
      break;
    }
  }

  writeInstallerMode(g_verbose);
}

int doInstall() {
  // wait for valid time
  setStatus(tici_device ? "Waiting for clock" : "waiting for clock");
  pushLog("waiting for valid system time");
  renderProgress(g_progress);
  while (!util::system_time_valid()) {
    util::sleep_for(500);
    LOGD("Waiting for valid time");
  }

  // cleanup previous install attempts
  setStatus(tici_device ? "Cleaning previous install" : "cleaning previous");
  pushLog("rm -rf " TMP_INSTALL_PATH);
  renderProgress(g_progress);
  run("rm -rf " TMP_INSTALL_PATH);

  // do the install
  if (util::file_exists(INSTALL_PATH) && util::file_exists(VALID_CACHE_PATH)) {
    return cachedFetch(INSTALL_PATH);
  } else {
    return freshClone();
  }
}

int freshClone() {
  LOGD("Doing fresh clone");
  setStatus(tici_device ? "Cloning repository" : "cloning repository");
  pushLog("git clone --depth=1 " + GIT_URL + " -b " + migrated_branch);
  renderProgress(0);
  std::string cmd = util::string_format("git clone --progress %s -b %s --depth=1 --recurse-submodules %s 2>&1",
                                        GIT_URL.c_str(), migrated_branch.c_str(), TMP_INSTALL_PATH);
  return executeGitCommand(cmd);
}

int cachedFetch(const std::string &cache) {
  LOGD("Fetching with cache: %s", cache.c_str());

  setStatus(tici_device ? "Using cached copy" : "using cache");
  pushLog("copy " + cache + " -> " TMP_INSTALL_PATH);
  renderProgress(2);
  run(util::string_format("cp -rp %s %s", cache.c_str(), TMP_INSTALL_PATH).c_str());
  run(util::string_format("cd %s && git remote set-url origin %s", TMP_INSTALL_PATH, GIT_URL.c_str()).c_str());
  run(util::string_format("cd %s && git remote set-branches --add origin %s", TMP_INSTALL_PATH, migrated_branch.c_str()).c_str());

  setStatus(tici_device ? "Fetching updates" : "fetching updates");
  pushLog("git fetch origin " + migrated_branch);
  renderProgress(10);

  return executeGitCommand(util::string_format("cd %s && git fetch --progress origin %s 2>&1", TMP_INSTALL_PATH, migrated_branch.c_str()));
}

int executeGitCommand(const std::string &cmd) {
  static const std::array stages = {
    // prefix, weight in percentage, status text
    std::tuple{"remote: Counting objects", 2, "counting objects"},
    std::tuple{"remote: Compressing objects", 3, "compressing"},
    std::tuple{"Receiving objects: ", 86, "receiving objects"},
    std::tuple{"Resolving deltas: ", 2, "resolving deltas"},
    std::tuple{"Updating files: ", 7, "updating files"},
  };

  FILE *pipe = popen(cmd.c_str(), "r");
  if (!pipe) return -1;

  char buffer[512];
  while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
    std::string line(buffer);
    pushLog(line);
    int base = 0;
    for (const auto &[text, weight, status] : stages) {
      if (line.find(text) != std::string::npos) {
        setStatus(status);
        size_t percentPos = line.find("%");
        if (percentPos != std::string::npos && percentPos >= 3) {
          try {
            int percent = std::stoi(line.substr(percentPos - 3, 3));
            int progress = base + int(percent / 100. * weight);
            renderProgress(progress);
          } catch (const std::exception &) {
            renderProgress(g_progress);
          }
        } else {
          renderProgress(g_progress);
        }
        break;
      }
      base += weight;
    }
    if (g_verbose) {
      renderProgress(g_progress);
    }
  }
  return pclose(pipe);
}

void cloneFinished(int exitCode) {
  LOGD("git finished with %d", exitCode);
  assert(exitCode == 0);

  renderProgress(100);

  // ensure correct branch is checked out
  int err = chdir(TMP_INSTALL_PATH);
  assert(err == 0);
  setStatus(tici_device ? "Checking out branch" : "checking out branch");
  pushLog("git checkout " + migrated_branch);
  renderProgress(100);
  run(("git checkout " + migrated_branch).c_str());
  run(("git reset --hard origin/" + migrated_branch).c_str());

  setStatus(tici_device ? "Updating submodules" : "updating submodules");
  pushLog("git submodule update --init");
  renderProgress(100);
  run("git submodule update --init");

  // move into place
  setStatus(tici_device ? "Moving into place" : "moving into place");
  pushLog("mv " TMP_INSTALL_PATH " " + INSTALL_PATH);
  renderProgress(100);
  run(("rm -f " + VALID_CACHE_PATH).c_str());
  run(("rm -rf " + INSTALL_PATH).c_str());
  run(util::string_format("mv %s %s", TMP_INSTALL_PATH, INSTALL_PATH.c_str()).c_str());

#ifdef INTERNAL
  run("mkdir -p /data/params/d/");

  // https://github.com/commaci2.keys
  const std::string ssh_keys = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMX2kU8eBZyEWmbq0tjMPxksWWVuIV/5l64GabcYbdpI";
  std::map<std::string, std::string> params = {
    {"SshEnabled", "1"},
    {"RecordFrontLock", "1"},
    {"GithubSshKeys", ssh_keys},
  };
  for (const auto& [key, value] : params) {
    std::ofstream param;
    param.open("/data/params/d/" + key);
    param << value;
    param.close();
  }
  run(("cd " + INSTALL_PATH + " && "
      "git remote set-url origin --push " GIT_SSH_URL " && "
      "git config --replace-all remote.origin.fetch \"+refs/heads/*:refs/remotes/origin/*\"").c_str());
#endif

  // write continue.sh
  setStatus(tici_device ? "Writing continue script" : "writing continue.sh");
  renderProgress(100);
  FILE *of = fopen("/data/continue.sh.new", "wb");
  assert(of != NULL);

  size_t num = str_continue_end - str_continue;
  size_t num_written = fwrite(str_continue, 1, num, of);
  assert(num == num_written);
  fclose(of);

  run("chmod +x /data/continue.sh.new");
  run("mv /data/continue.sh.new " CONTINUE_PATH);

  // wait for the installed software's UI to take over
  finishInstall();
}

int main(int argc, char *argv[]) {
  if (tici_device) {
    InitWindow(2160, 1080, "Installer");
  } else {
    InitWindow(536, 240, "Installer");
  }

  font_inter = LoadFontFromMemory(".ttf", inter_ttf, inter_ttf_end - inter_ttf, FONT_SIZE, NULL, 0);
  font_roman = LoadFontFromMemory(".ttf", inter_light_ttf, inter_light_ttf_end - inter_light_ttf, FONT_SIZE, NULL, 0);
  font_display = LoadFontFromMemory(".ttf", inter_bold_ttf, inter_bold_ttf_end - inter_bold_ttf, FONT_SIZE, NULL, 0);
  SetTextureFilter(font_inter.texture, TEXTURE_FILTER_BILINEAR);
  SetTextureFilter(font_roman.texture, TEXTURE_FILTER_BILINEAR);
  SetTextureFilter(font_display.texture, TEXTURE_FILTER_BILINEAR);

  branchMigration();

  if (util::file_exists(CONTINUE_PATH)) {
    finishInstall();
  } else {
    promptInstallMode();
    renderProgress(0);
    int result = doInstall();
    cloneFinished(result);
  }

  CloseWindow();
  UnloadFont(font_inter);
  UnloadFont(font_roman);
  UnloadFont(font_display);
  return 0;
}

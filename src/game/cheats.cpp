// The launcher's cheats (settings.toml's god_mode and infinite_ammo): the players' health is kept full, the hit
// handler is given no damage, and every ammo count stays at 500. NightFire's actor has its health at +0x824 (and the
// co-op copy at +0x848), and the ammo counts as 16-bit words at +0x114 + index * 2 (the weapon table's +0x90 names
// the index; 0xB9EB0 reads them, 0xBA5E0 adds to them).
#include <cmath>

#include "app/app.h"
#include "common/nightfire.h"
#include "kernel/kernel.h"

namespace nf {
void CheatsFrame() {
    const app::Settings& s = app::Get();
    if (!s.god_mode && !s.infinite_ammo) return;
    for (uint32_t p = 0; p < 4; p++) {
        const uint32_t obj = kernel::R32(0x1F6654 + 4 * p);
        if (obj < 0x10000 || (obj & 0x7FFFFFFF) >= 0x08000000) continue;
        const uint32_t actor = kernel::R32(obj + 0xBC);
        if (actor < 0x10000 || (actor & 0x7FFFFFFF) >= 0x08000000) continue;
        if (s.god_mode) {
            for (uint32_t off : {0x824u, 0x848u}) {
                const float health = kernel::G<float>(actor + off);
                if (std::isfinite(health) && health > 0 && health < 100) kernel::G<float>(actor + off) = 100.0f;
            }
        }
        if (s.infinite_ammo)
            for (uint32_t i = 0; i < 32; i++) kernel::G<uint16_t>(actor + 0x114 + i * 2) = 500;
    }
}
}  // namespace nf

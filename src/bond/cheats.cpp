// The launcher's cheats (settings.toml's god_mode and infinite_ammo) in bond_eng.xbe: the player's gentity health is
// kept full (the entity's +0xC is its gentity, health a float at +0x2C4), the damage event is given 0, and every
// inventory item's ammo type is topped up through the player's vfunc +0x100 ("ammo", type, amount, 0).
#include <algorithm>
#include <cstring>

#include "app/app.h"
#include "bond/addr.h"
#include "common/auf.h"
#include "kernel/kernel.h"

namespace {
uint32_t HealthAddress(uint32_t player) {
    const uint32_t g = player ? kernel::R32(player + 0xC) : 0;
    return g ? g + 0x2C4 : 0;
}

void Ammo(X86Context& ctx, uint32_t player) {
    const uint32_t vt = kernel::R32(player), count = std::min<uint32_t>(kernel::R32(player + 0x318), 64);
    if (!vt || !count) return;
    const uint32_t esp = ctx.esp, ecx = ctx.ecx, eax = ctx.eax;
    ctx.esp = esp - 64;
    const uint32_t ammo = ctx.esp;
    std::memcpy(&kernel::G<uint8_t>(ammo), "ammo", 5);
    ctx.ecx = player;
    uint32_t item = kernel::CallGuest(ctx, kernel::R32(vt + 0x9C), {0, 0, 0});
    for (uint32_t i = 0; i < count && item; i++) {
        for (uint32_t slot : {0x1DCu, 0x1E8u}) {
            ctx.ecx = item;
            const uint32_t type = kernel::CallGuest(ctx, kernel::R32(kernel::R32(item) + slot), {});
            if (type && kernel::G<uint8_t>(type)) {
                ctx.ecx = player;
                kernel::CallGuest(ctx, kernel::R32(vt + 0x100), {ammo, type, 500, 0});
            }
        }
        ctx.ecx = player;
        const uint32_t next = kernel::CallGuest(ctx, kernel::R32(vt + 0xC0), {item, 0});
        if (next == item) break;
        item = next;
    }
    ctx.esp = esp;
    ctx.ecx = ecx;
    ctx.eax = eax;
}
}  // namespace

namespace auf {
void CheatsFrame(X86Context& ctx, uint32_t player) {
    const app::Settings& s = app::Get();
    if (!player || (!s.god_mode && !s.infinite_ammo)) return;
    if (s.god_mode) {
        if (const uint32_t at = HealthAddress(player)) {
            float health;
            std::memcpy(&health, &kernel::G<uint32_t>(at), 4);
            if (health > 0 && health < 100) {
                health = 100;
                std::memcpy(&kernel::G<uint32_t>(at), &health, 4);
            }
        }
    }
    if (s.infinite_ammo) {
        static uint32_t frame = 0;
        if (++frame % 60 == 0) Ammo(ctx, player);
    }
}
}  // namespace auf

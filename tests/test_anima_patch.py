"""Tests offline del mapeo puro del nodo `waifu_anima_patch` (UI del backlog 5).

El modulo vive en `tools/custom_nodes/waifu_anima_patch/mapping.py` (stdlib
puro); se carga por ruta para no depender de ComfyUI ni de torch y para que la
suite corra en cualquier copia del repo.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "custom_nodes"
    / "waifu_anima_patch"
    / "mapping.py"
)

spec = importlib.util.spec_from_file_location("waifu_anima_patch_mapping", SOURCE)
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)

TABLA_PUBLICADA = {
    0: 0,
    1: 1,
    2: 3,
    3: 4,
    4: 6,
    5: 7,
    6: 9,
    7: 10,
    8: 12,
    9: 13,
    10: 15,
    11: 16,
    12: 18,
    13: 19,
    14: 20,
    15: 22,
    16: 23,
    17: 25,
    18: 26,
    19: 28,
    20: 29,
    21: 31,
    22: 32,
    23: 34,
    24: 35,
    25: 37,
    26: 38,
    27: 39,
}


class TablaCanonicaTests(unittest.TestCase):
    def test_posiciones_insertadas_canonicas(self):
        self.assertEqual(
            mapping.INSERTED_BLOCK_POSITIONS,
            (2, 5, 8, 11, 14, 17, 21, 24, 27, 30, 33, 36),
        )

    def test_tabla_old_to_new_publicada(self):
        self.assertEqual(mapping.OLD_BLOCK_TO_EXPANDED, TABLA_PUBLICADA)

    def test_tabla_biyectiva_y_sin_posiciones_insertadas(self):
        destinos = list(mapping.OLD_BLOCK_TO_EXPANDED.values())
        self.assertEqual(len(set(destinos)), len(destinos))
        self.assertEqual(sorted(destinos), sorted(set(range(40)) - set(
            mapping.INSERTED_BLOCK_POSITIONS
        )))
        for destino in destinos:
            self.assertNotIn(destino, mapping.INSERTED_BLOCK_POSITIONS)
        self.assertEqual(mapping.ANIMA_BASE_BLOCKS, 28)
        self.assertEqual(mapping.ANIMA_EXPANDED_BLOCKS, 40)


class BuildKeyMapTests(unittest.TestCase):
    def _dense_kohya(self, blocks=28):
        keys = []
        for block in range(blocks):
            for suffix in (
                "cross_attn_k_proj.lora_down.weight",
                "cross_attn_k_proj.lora_up.weight",
                "cross_attn_k_proj.alpha",
                "mlp_layer1.lora_down.weight",
            ):
                keys.append(f"lora_unet_blocks_{block}_{suffix}")
        return keys

    def test_kohya_base28_remap_completo(self):
        keys = self._dense_kohya()
        remap, report = mapping.build_key_map(keys)
        self.assertEqual(report["layout"], mapping.LAYOUT_BASE28)
        # bloques 0 y 1 conservan indice: 26 bloques x 4 claves cambian.
        self.assertEqual(report["remapped"], 26 * 4)
        self.assertEqual(len(remap), 26 * 4)
        self.assertNotIn("lora_unet_blocks_0_cross_attn_k_proj.alpha", remap)
        self.assertEqual(
            remap["lora_unet_blocks_2_cross_attn_k_proj.alpha"],
            "lora_unet_blocks_3_cross_attn_k_proj.alpha",
        )
        self.assertEqual(
            remap["lora_unet_blocks_27_mlp_layer1.lora_down.weight"],
            "lora_unet_blocks_39_mlp_layer1.lora_down.weight",
        )
        for old, new in remap.items():
            old_block = int(old.split("_")[3])
            new_block = int(new.split("_")[3])
            self.assertEqual(new_block, TABLA_PUBLICADA[old_block])
            self.assertEqual(old.split("_", 4)[4], new.split("_", 4)[4])

    def test_kohya_sparse_sigue_siendo_base28(self):
        keys = [f"lora_unet_blocks_{block}_self_attn_q_proj.alpha" for block in range(6)]
        remap, report = mapping.build_key_map(keys)
        self.assertEqual(report["layout"], mapping.LAYOUT_BASE28)
        self.assertEqual(report["dit_blocks"], [0, 1, 2, 3, 4, 5])

    def test_peft_base28(self):
        keys = [
            "diffusion_model.blocks.12.self_attn.q_proj.lora_A.weight",
            "diffusion_model.blocks.27.self_attn.q_proj.lora_B.weight",
            "diffusion_model.blocks.0.self_attn.q_proj.lora_A.weight",
        ]
        remap, report = mapping.build_key_map(keys)
        self.assertEqual(report["layout"], mapping.LAYOUT_BASE28)
        self.assertEqual(
            remap["diffusion_model.blocks.12.self_attn.q_proj.lora_A.weight"],
            "diffusion_model.blocks.18.self_attn.q_proj.lora_A.weight",
        )
        self.assertEqual(
            remap["diffusion_model.blocks.27.self_attn.q_proj.lora_B.weight"],
            "diffusion_model.blocks.39.self_attn.q_proj.lora_B.weight",
        )
        self.assertNotIn(
            "diffusion_model.blocks.0.self_attn.q_proj.lora_A.weight", remap
        )

    def test_ya_expandido_no_se_toca(self):
        keys = self._dense_kohya(blocks=40)
        remap, report = mapping.build_key_map(keys)
        self.assertEqual(report["layout"], mapping.LAYOUT_EXPANDED)
        self.assertEqual(remap, {})
        self.assertEqual(report["remapped"], 0)

    def test_claves_no_dit_intactas(self):
        keys = [
            "lora_te_layers_2_self_attn_q_proj.lora_down.weight",
            "lora_unet_llm_adapter_blocks_0_attn_q_proj.alpha",
            "diffusion_model.llm_adapter.blocks.0.attn.q_proj.lora_A.weight",
            "lora_unet_blocks_2_cross_attn_k_proj.alpha",
        ]
        remap, report = mapping.build_key_map(keys)
        self.assertEqual(report["layout"], mapping.LAYOUT_BASE28)
        self.assertEqual(
            remap, {
                "lora_unet_blocks_2_cross_attn_k_proj.alpha":
                    "lora_unet_blocks_3_cross_attn_k_proj.alpha",
            }
        )
        for clave in (
            "lora_te_layers_2_self_attn_q_proj.lora_down.weight",
            "lora_unet_llm_adapter_blocks_0_attn_q_proj.alpha",
            "diffusion_model.llm_adapter.blocks.0.attn.q_proj.lora_A.weight",
        ):
            self.assertNotIn(clave, remap)

    def test_sin_bloques_dit(self):
        remap, report = mapping.build_key_map(["lora_te_layers_1_foo.alpha"])
        self.assertEqual(report["layout"], mapping.LAYOUT_NO_DIT)
        self.assertEqual(remap, {})


class RemapStateDictTests(unittest.TestCase):
    def test_remap_preserva_valores_y_no_muta_el_original(self):
        sd = {
            "lora_unet_blocks_2_cross_attn_k_proj.alpha": "A",
            "lora_unet_blocks_27_mlp_layer1.lora_up.weight": "B",
            "lora_te_layers_0_mlp_down_proj.alpha": "C",
        }
        remapped, report = mapping.remap_state_dict(sd)
        self.assertEqual(report["remapped"], 2)
        self.assertEqual(remapped["lora_unet_blocks_3_cross_attn_k_proj.alpha"], "A")
        self.assertEqual(
            remapped["lora_unet_blocks_39_mlp_layer1.lora_up.weight"], "B"
        )
        self.assertEqual(remapped["lora_te_layers_0_mlp_down_proj.alpha"], "C")
        self.assertEqual(
            set(sd),
            {
                "lora_unet_blocks_2_cross_attn_k_proj.alpha",
                "lora_unet_blocks_27_mlp_layer1.lora_up.weight",
                "lora_te_layers_0_mlp_down_proj.alpha",
            },
        )

    def test_remap_nativo_devuelve_copia(self):
        sd = {"lora_unet_blocks_30_self_attn_q_proj.alpha": "A"}
        remapped, report = mapping.remap_state_dict(sd)
        self.assertEqual(report["layout"], mapping.LAYOUT_EXPANDED)
        self.assertEqual(remapped, sd)
        self.assertIsNot(remapped, sd)


class LoRAsRealesTests(unittest.TestCase):
    """Smoke opcional contra los LoRAs Anima del usuario (si existen)."""

    LORAS = Path(
        r"E:\IA\WAIFU\ComfyUI\models\loras\anima"
    )

    def _claves_reales(self, path: Path) -> list[str]:
        import json
        import struct

        with open(path, "rb") as handle:
            (length,) = struct.unpack("<Q", handle.read(8))
            header = json.loads(handle.read(length).decode("utf-8"))
        header.pop("__metadata__", None)
        return list(header)

    def test_miku_detectado_base28(self):
        path = self.LORAS / "Miku_Nakano_Anima_v0.7.safetensors"
        if not path.is_file():
            self.skipTest("LoRA de Miku no presente en esta maquina")
        remap, report = mapping.build_key_map(self._claves_reales(path))
        if report["layout"] == mapping.LAYOUT_BASE28:
            self.assertGreater(report["remapped"], 0)
            self.assertTrue(
                all(clave.startswith("lora_unet_blocks_") for clave in remap)
            )
            self.assertEqual(report["dit_blocks"], list(range(28)))
        else:
            # Si el archivo local se sustituye por un LoRA nativo del modelo
            # expandido, no debe remapearse nada.
            self.assertEqual(report["layout"], mapping.LAYOUT_EXPANDED)
            self.assertEqual(remap, {})


if __name__ == "__main__":
    unittest.main()

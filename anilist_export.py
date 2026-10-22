"""Exportador de mutaciones AniList (replay manual) — MÓDULO PURO y OFFLINE.

Miraru puede sincronizar en vivo con AniList solo si el usuario conectó su
cuenta OAuth (ver anilist_sync.py). Cuando NO hay conexión, este módulo
compone los cuerpos GraphQL listos para enviar (payloads) de la mutación
`SaveMediaListEntry` de AniList: la ruta POST /api/export/anilist los devuelve
en JSON y el USUARIO los reproduce (replay) a mano contra el endpoint oficial
(https://graphql.anilist.co, igual que anilist_sync.ANILIST_API) con SU PROPIO
token. Ninguna función de aquí toca la red: todo es composición de dicts.

Elección de escala de puntuación (documentada a propósito): Miraru asume la
escala 0–100 de AniList vía el argumento `scoreRaw` — la misma que usa
anilist_sync.push_anime (puntuacion * 10, comentario: "AniList scoreRaw es
0-100") y el mismo sufijo scoreRaw permite al servidor distinguir el formato.
Sin puntuación real (None o 0) el campo NO se envía para no borrar la nota que
ya tenga la entrada en AniList.

Formato de cada mutación (decisión: plantilla GraphQL POR ÍTEM): cada elemento
es exactamente el cuerpo JSON que se debe POSTEAR a AniList
({"query": ..., "variables": {...}}), de modo que "replay" sea copiar el dict
íntegro. La plantilla completa viaja una vez por mutación (no una global).
"""

from __future__ import annotations

from typing import Any, Optional

# ── Plantilla GraphQL (una sola, compartida por referencia) ──────────────────

# Espejo de la mutación de PUSH de anilist_sync._SAVE_ENTRY (mismas formas:
# $mediaId/, $status/, scoreRaw, progress) con lo que añade el export:
# progressVolumes (tomos de manga) y userId opcional del viewer al que
# pertenece la lista. Variables declaradas pero ausentes coaccionan a null →
# AniList interpreta null como "no tocar ese campo".
_MUTACION = """\
mutation ($mediaId: Int!, $status: MediaListStatus, $scoreRaw: Int,
          $progress: Int, $progressVolumes: Int, $userId: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status,
                     scoreRaw: $scoreRaw, progress: $progress,
                     progressVolumes: $progressVolumes, userId: $userId) {
    id mediaId status score progress progressVolumes
  }
}
"""

# ── Mapeos (idénticos a los de anilist_sync, aquí en copia local para que el
#    módulo siga siendo puro e independiente de la capa de red) ───────────────

# Espejo de anilist_sync._STATUS_TO_ANILIST + alias históricos: la BD guarda
# "pausa" (canónico desde el import XML de MAL, ver database._RANGO_ESTADO),
# pero registros antiguos pueden tener "en pausa" o "pausado". Estado
# desconocido o ausente → PLANNING (la salida segura de anilist_sync).
_ESTADO_A_ANILIST = {
    "viendo": "CURRENT",
    "completado": "COMPLETED",
    "pendiente": "PLANNING",
    "abandonado": "DROPPED",
    "pausa": "PAUSED",
    "en pausa": "PAUSED",
    "pausado": "PAUSED",
}


def _a_int(valor: Any) -> int:
    """Convierte a int de forma indulgente: None/''/'malo' → 0."""
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _score_raw(puntuacion: Any) -> Optional[int]:
    """Puntuación de Miraru (0–10) → scoreRaw de AniList (0–100).

    Redondeo al entero más cercano (round de Python: mitades al par, por eso
    75.5→76 y 83.5→84) y recorte al rango válido 0–100. Sin puntuación real
    (None, no numérica o 0) devuelve None: el campo no se envía.
    """
    try:
        f = float(puntuacion)
    except (TypeError, ValueError):
        return None
    if not f:  # 0 y 0.0: "sin nota real" (guarda el patrón de anilist_sync)
        return None
    return max(0, min(100, round(f * 10)))


def build_mutation(lista: list[dict], token_user_id: int = 0) -> list[dict]:
    """Compone (OFFLINE, sin red) las mutaciones SaveMediaListEntry.

    - lista: los dicts que devuelve database.listar_animes()/listar_animes_slim()
      (solo se leen nombre/agregados con .get, nunca se valida su forma).
    - token_user_id: id del viewer de AniList (0 → no se envía el userId,
      AniList deduce el usuario del token con que se replaye).

    Devuelve una lista de cuerpos JSON listos para POST a graphql.anilist.co:
    cada item es {"query": _MUTACION, "variables": {...}}. Se omite cualquier
    anime sin anilist_id (>0). Exige del caller comprobar si la lista salió
    vacía (es el caso de error de la ruta HTTP).
    """
    mutaciones: list[dict] = []
    for anime in lista or []:
        anilist_id = _a_int(anime.get("anilist_id"))
        if anilist_id <= 0:
            continue  # sin id de AniList: nada que exportar para este anime

        estado = str(anime.get("estado_usuario") or "").strip().lower()
        variables: dict[str, Any] = {
            "mediaId": anilist_id,
            "status": _ESTADO_A_ANILIST.get(estado, "PLANNING"),
            # episodios_vistos es el contador de progreso de Miraru (para
            # manga se reutiliza como capítulos leídos → progress de AniList)
            "progress": max(0, _a_int(anime.get("episodios_vistos"))),
        }

        # Solo manga: progreso de tomos → progressVolumes (Miraru guarda
        # los tomos leídos en volumenes_leidos; 0 → no se envía).
        if (anime.get("tipo") or "") == "manga":
            tomos = _a_int(anime.get("volumenes_leidos"))
            if tomos > 0:
                variables["progressVolumes"] = tomos

        raw = _score_raw(anime.get("puntuacion"))
        if raw is not None:
            variables["scoreRaw"] = raw

        if token_user_id:
            variables["userId"] = int(token_user_id)

        mutaciones.append({"query": _MUTACION, "variables": variables})
    return mutaciones

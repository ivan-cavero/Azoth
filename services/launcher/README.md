# Azoth launcher

Launcher **propio**. En private no usamos Steam ni Easy Anti-Cheat.

Responsabilidades:

1. **Install / update** del cliente ya preparado para nuestro server (exe sin EAC, URLs/pin nuestros, PAKs vanilla + contenido custom).
2. **Play** — arranca `Bin64\NewWorld.exe` directo.
3. En el futuro: parches de contenido, UI, news de *nuestro* CMS.

## Steam

Steam **solo** existe en el perfil official (`research/`). El launcher private no lo llama. El seed inicial del cliente es la copia que **tú ya compraste** (árbol de archivos del install). No vamos a montar un CDN pirata del juego de Amazon: el operador parte de su install legal; el launcher reparte **nuestros** parches y packs encima.

## Spike ahora

`src/Start-NwPrivate.ps1` — Steam puede estar abierto o no; el script lanza el exe directo y registra si aparece `EasyAntiCheat_EOS.exe` y si Game.log llega a frontend. Aún no está medido en el build 1.400.

Docs: [docs/LAUNCHER.md](docs/LAUNCHER.md).

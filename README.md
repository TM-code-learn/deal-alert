# Deal alert — jeux vidéo / consoles / accessoires

Alertes Telegram sur les bons plans jeux vidéo (flux RSS Dealabs), exécutées toutes les 30 min par GitHub Actions.

## Secrets requis
Settings → Secrets and variables → Actions : `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`.

## Personnaliser (`config.json`)
- `keywords` : un deal est retenu s'il contient au moins un mot-clé.
- `exclude` : mots qui éliminent un deal.
- `max_price` : prix max en € (ex. `80`), `null` = pas de limite.
- `feeds` : flux RSS surveillés (le nombre d'entrées s'affiche dans les logs Actions).

La 1re exécution mémorise les deals existants sans alerter ; les alertes arrivent ensuite.

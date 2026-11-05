# Monitor Solana

Painel em Python (Flask) que, **a cada 1 minuto**:

1. Busca o volume de compra (estimado) das moedas e monta o ranking (maior no topo).
2. Lista as maiores carteiras (holders) de cada moeda.
3. Identifica a carteira criadora e as moedas vinculadas a ela (pump.fun).

Moedas: Goatseus Maximus, Peanut the Squirrel, Moo Deng (edite a lista `TOKENS` em `app.py`).

## Rodar local
```bash
pip install -r requirements.txt
python app.py   # http://localhost:5000
```

## Publicar
O GitHub Pages **não executa Python**. Suba o código no GitHub e faça deploy em Render, Railway ou Fly.io
(o `Procfile` já está pronto: `gunicorn --workers 1`, necessário para o ciclo de 1 min rodar em segundo plano).
GitHub Actions com cron só roda a cada 5 min no mínimo, por isso não serve para o ciclo de 1 min.

## Variáveis de ambiente
- `SOLANA_RPC`: RPC próprio (Helius, QuickNode). O RPC público tem limite de requisições.
- `INTERVAL_SECONDS`: intervalo do ciclo (padrão 60).

## Limitações
- "Volume de compra" = volume do par × proporção de transações de compra (DexScreener não informa o valor exato).
- A maior carteira costuma ser o pool de liquidez/bonding curve.
- Criador: usa a API do pump.fun; se indisponível, usa a mint authority como aproximação.
- Não é recomendação financeira.

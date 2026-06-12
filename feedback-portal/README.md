# Portal de Feedback ONYX DOJO

Site separado para receber, moderar e publicar feedbacks de alunos, pais, mães e responsáveis.

## Como rodar

```powershell
cd feedback-portal
.\run_portal.ps1
```

Depois acesse:

- Envio de feedback: http://localhost:8000/
- Feedbacks aprovados: http://localhost:8000/feedbacks.html
- Painel administrativo: http://localhost:8000/admin.html

## Login administrativo

Por padrao, em ambiente local:

- Usuario: `admin`
- Usuario: `onyxdojo2026`
- Senha: `admin200`

Em producao, configure variaveis de ambiente antes de iniciar:

```powershell
$env:ONYX_ADMIN_USER="seu_usuario"
$env:ONYX_ADMIN_PASSWORD="sua_senha_forte"
$env:ONYX_SESSION_SECRET="um_segredo_longo"
python backend/app.py
```

## API para o site publico

Endpoint publico para integrar no site principal:

```text
GET /api/public/feedbacks
```

Retorna apenas feedbacks `Aprovado` e autorizados para publicacao.

## Estrutura

```text
feedback-portal/
  backend/
    app.py
  database/
    .gitkeep
  frontend/
    admin.html
    feedbacks.html
    index.html
    scripts/
      admin.js
      feedbacks.js
      form.js
    styles/
      main.css
```

O banco SQLite e criado automaticamente em `database/feedbacks.sqlite3`.

## Usando Supabase

1. Crie um projeto no Supabase.
2. Abra `SQL Editor` no Supabase.
3. Rode o conteudo deste arquivo:

```text
database/supabase_schema.sql
```

4. Configure as variaveis de ambiente antes de iniciar:

```powershell
$env:SUPABASE_URL="https://seu-projeto.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY="sua_service_role_key"
$env:ONYX_SESSION_SECRET="um_segredo_longo"
.\run_portal.ps1
```

Use a `service_role_key` somente no back-end. Nunca coloque essa chave em arquivo JavaScript publico.

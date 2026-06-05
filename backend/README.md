# Backend do Bot de Trading Institucional SMC

Este diretório contém o backend da aplicação, desenvolvido com FastAPI, para gerenciar a conexão e as operações de trading na plataforma Quotex.

## Configuração

1.  **Instalar dependências:**

    ```bash
    pip install -r requirements.txt
    ```

2.  **Variáveis de Ambiente:**

    Crie um ficheiro `.env` na raiz do diretório `/backend` com as suas credenciais da Quotex:

    ```
    QUOTEX_EMAIL=seu_email@example.com
    QUOTEX_PASSWORD=sua_senha
    ```

    **ATENÇÃO:** Nunca partilhe o seu ficheiro `.env` nem as suas credenciais.

## Como Executar

Para iniciar o servidor FastAPI, execute o seguinte comando no diretório `/backend`:

```bash
uvicorn main:app --reload
```

O servidor estará disponível em `http://127.0.0.1:8000`.

## Endpoints da API

-   **GET /**: Retorna o status do bot e os endpoints disponíveis.
-   **POST /connect-demo**: Conecta à conta DEMO da Quotex.
-   **POST /connect-real**: Conecta à conta REAL da Quotex (requer confirmação).
-   **POST /trade**: Executa uma ordem de trading.
-   **GET /balance**: Retorna o saldo da conta (DEMO ou REAL).
-   **POST /switch-mode**: Alterna entre os modos DEMO e REAL.
-   **POST /kill-switch**: Ativa o Kill Switch, desativando todas as operações.
-   **POST /reset**: Reseta os contadores de perda diária e o Kill Switch.
-   **GET /health**: Verifica a saúde do serviço e o status atual do bot.

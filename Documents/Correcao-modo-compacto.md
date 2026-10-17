# Correção do modo compacto

Problema identificado: a janela Tkinter tinha apenas entrada de texto e botão
de envio. Não havia captura de microfone nem tratamento do evento de áudio
do servidor. O estado Falando podia aparecer sem som. Além disso, --compact
sozinho não encaminhava para o lançador da janela.

Correções: controles Ativar escuta/Desativar escuta e Interromper; captura em
thread, envio de WAV ao servidor, reprodução de MP3 por reprodutor instalado,
descarte de áudio antigo após interrupção e limpeza dos recursos ao fechar.
O cliente anuncia explicitamente o modo de voz do servidor. Reutiliza servidor
Jarvis existente e verifica se a porta está ocupada por outro serviço.

Validação: suíte automatizada e criação real de uma janela oculta. O teste
não ativou o microfone real nem produziu som. A escuta do hardware deve ser
validada pelo usuário no botão Ativar escuta. Durante as respostas, o modo
compacto pausa o envio de áudio para evitar eco; Interromper corta a fala.

Para abrir a versão corrigida, feche a janela antiga e execute no projeto:
.venv\Scripts\python.exe -m jarvis.app --compact

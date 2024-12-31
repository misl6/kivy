@echo off

:: Caminho do arquivo a ser "salvo"
@REM set "file=kivy\core\skia\skia_wrapper.pyx"
set "file=kivy\core\skia\pure_skia.pyx"

:: Atualiza a data de modificação (simulando Ctrl+S)
echo Salvando skia_wrapper.pyx...
powershell -Command "(Get-Item '%file%').LastWriteTime = Get-Date"

:: Compila as extensões
echo Compilando as extensões...
python setup.py build_ext --inplace
if errorlevel 1 (
    echo Erro na compilacao das extensoes. Abortando script.
    exit /b 1
)

:: Executa os testes
echo Executando os testes...
@REM python .\skia_tests_gl_rendering.py
python .\main.py
if errorlevel 1 (
    echo Erro ao executar os testes. Abortando script.
    exit /b 1
)

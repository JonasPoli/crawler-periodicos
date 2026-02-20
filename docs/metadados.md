# Metadados

Vamos montar um novo crawler para coletar os metadados dos artigos.
Os artigos possuem a URL.
Deve-se criar um crawler que colete os metadados do artigo e salva-los no banco de dados abriando cada uma das URLs dos
artigos.

Um dos trabalhos fundamentais e abrir pelo menos 1 artigo aleatoriamente de cada um dos periódicos e verificar como os metadados estão sendo apresentados para se construir as expressões regulares e as rotinas de extração de dados de cada um dos modelos de periódicos.

Deve sempre se levar em consideração de que o crawler pode ser executado diversas vezes e tudo que for analisado deve
antes verificar se é uma inserção ou uma alteração.

## Título correto
Deve se identificar para cada um dos periódicos, quando aberto a url do artigo, onde fica o título, como por exemplo, em
h1
Assim que identificar como extrair o título, a expressão regular deve ser salva no cadastro do periódico

## Autores
Os autores devem ser identificados para cada um dos modelos de periódicos
Assim que identificar como extrair o autor, a expressão regular deve ser salva no cadastro do periódico
Entenda que existe um cadastro de autores, que agora pode possuir novos campos, como o orcid.
Deve se ter uma tabela auxiliar para informar qual autor pertence a qual artigo.
Deve se tomar o cuidado para não cadastrar autores que já existem na tabela de autores.
```html
<section class="item authors">
    <h2 class="pkp_screen_reader">Autores</h2>
    <ul class="authors">
        <li>
            <span class="name">
                Marileusa Cecília Carvalho
            </span>
            <span class="orcid">

                <a href="https://orcid.org/0009-0006-4822-7054" target="_blank">
                    https://orcid.org/0009-0006-4822-7054
                </a>
            </span>
        </li>
        <li>
            <span class="name">
                Ricardo Tavares Camargo Martins
            </span>
            <span class="orcid">

                <a href="https://orcid.org/0009-0007-6190-8898" target="_blank">
                    https://orcid.org/0009-0007-6190-8898
                </a>
            </span>
        </li>
    </ul>
</section>
```

## Palavras-chave
As palavras-chave devem ser identificadas para cada um dos modelos de periódicos
Assim que identificar como extrair as palavras-chave, a expressão regular deve ser salva no cadastro do periódico
Entenda que deve existir um cadastro de palavras-chave.
Deve se ter uma tabela auxiliar para informar qual palavra-chave existe para qual artigo.
```html
<section class="item keywords">
				<h2 class="label">
										Palavras-chave:
				</h2>
				<span class="value">
											Temas Transcversais, Saúde Infantil, Sustentabilidade, Literatura Infantil, Contação de Histórias									</span>
</section>
```
ou as vezes
```html
<p><strong>Palavras-chave:</strong><br>avaliação de desempenho; transparência; responsabilidade; universidades públicas; Portugal</p>


## Resumo
O Resumo devem ser identificado para cada um dos modelos de periódicos
Assim que identificar como extrair as Resumos, a expressão regular deve ser salva no cadastro do periódico
Entenda que Resumo deve ser um campo novo no cadastro do artigo.

```html
<section class="item abstract">
					<h2 class="label">Resumo</h2>
					<p>Este artigo discute a importância dos temas transversais na educação infantil, com ênfase na saúde e sua relação direta com a sustentabilidade. Considerando que tais temas constituem componentes essenciais na formação integral das crianças, o estudo propõe uma estratégia pedagógica baseada na literatura infantil, utilizando a obra Higiene, Ordem e Saúde como eixo estruturante. A partir de uma abordagem qualitativa, de caráter teórico-reflexivo, discute-se como a contação de histórias e a criação de ambientes lúdicos — como o acampamento pedagógico — favorecem aprendizagens significativas, estimulam hábitos de autocuidado e promovem valores socioambientais. A fundamentação teórica dialoga com autores da educação, literatura infantil e sustentabilidade, evidenciando que a transversalidade permite integrar dimensões físicas, emocionais e ambientais do cuidado humano. Conclui-se que a literatura infantil, aliada às metodologias ativas, constitui recurso potente para trabalhar saúde e sustentabilidade de maneira dinâmica e sensível na educação infantil.</p>
</section>
```


## Referências
As referências devem ser identificadas para cada um dos modelos de periódicos
Assim que identificar como extrair as referências, a expressão regular deve ser salva no cadastro do periódico
Entenda que deve existir um cadastro de referências.
Deve se ter uma tabela auxiliar para informar qual referência existe para qual artigo.
Deve se tomar o cuidado para não cadastrar referências que já existem na tabela de referências.
```html
<section class="item references">
					<h2 class="label">
						Referências
					</h2>
					<div class="value">
																					<p>Abramovich, F. (1997). Literatura infantil: gostosuras e bobices (11ª ed.). Scipione. </p>
															<p>Barbosa, A. B. S. (2017). Saúde mental na infância: Um guia prático para pais e educadores. Cortez. </p>
															<p>Bombassaro, T. (2010). Cidadania e ética: Fundamentos filosóficos dos temas transversais. EDIPUCRS. </p>
															<p>Brasil. Ministério da Educação. (2018). Base Nacional Comum Curricular. MEC. </p>
															<p>Brasil. Ministério da Educação. (1998). Parâmetros Curriculares Nacionais: Temas Transversais. MEC/SEF. </p>
															<p>Brundtland, G. H. (1987). Our common future. Oxford University Press. </p>
															<p>Carvalho, M. H. C. de. (2010). Literatura infantil e formação de leitores. Cortez. </p>
															<p>Coelho, N. N. (2000). Literatura infantil: Teoria, análise e didática. Moderna. </p>
															<p>Debus, E. (1996). A escola e a literatura infantil. Papirus. </p>
															<p>Figueiredo, E., &amp; Andrade, R. (2004). Os temas transversais e a educação para a cidadania: Perspectivas históricas e desafios contemporâneos. Revista Electrónica Interuniversitaria de Formación del Profesorado, 7(3). </p>
															<p>Freire, P. (1996). Pedagogia da autonomia: Saberes necessários à prática educativa. Paz e Terra. </p>
															<p>Green, J., Brown, T., &amp; Williams, A. (2019). Health education in schools: A vital component of comprehensive health promotion. Health Education Journal, 78(4), 456–470. <a href="https://doi.org/10.1177/0017896918798072">https://doi.org/10.1177/0017896918798072</a> </p>
															<p>Instituto de Pesquisa Econômica Aplicada. (2022). Saúde mental de crianças e adolescentes no Brasil: Desigualdades e desafios. IPEA. </p>
															<p>Jacobi, P. (2003). Educação ambiental, cidadania e sustentabilidade. Cadernos de Pesquisa, 118, 189–205.  
DOI: <a href="https://doi.org/10.1590/S0100-15742003000100008">https://doi.org/10.1590/S0100-15742003000100008</a>
</p>
															<p>Lajolo, M. (2008). Do mundo da leitura para a leitura do mundo (3ª ed.). Ática. </p>
															<p>Loureiro, C. F. B. (2004). Educação ambiental: Questões de vida. Cortez. </p>
															<p>Oliveira, M. R. (2016). Educação para a sustentabilidade: Um novo paradigma educacional. Revista Brasileira de Educação, 21(64), 475–496. <a href="https://doi.org/10.1590/S1413-24782016216425">https://doi.org/10.1590/S1413-24782016216425</a> </p>
															<p>Organização Mundial da Saúde. (2020). Constituição da OMS. OMS. </p>
															<p>Sacristán, J. G. (2000). O currículo: Uma reflexão sobre a prática. Artmed. </p>
															<p>Sato, M., &amp; Carvalho, I. C. M. (2005). Educação ambiental: Pesquisa e desafios. Artmed. </p>
															<p>SB Brasil. Ministério da Saúde. (2020). Pesquisa Nacional de Saúde Bucal: Resultados principais. </p>
															<p>Silva, P. R. (2015). Sustentabilidade e saúde: Uma abordagem integrada. Revista de Saúde Pública, 49, 78–85. <a href="https://doi.org/10.1590/S0034-8910.2015049005849">https://doi.org/10.1590/S0034-8910.2015049005849</a> </p>
															<p>Smith, J., Peterson, L., &amp; Hansen, R. (2017). The importance of health education in the classroom. Journal of School Health, 87, 623–630. <a href="https://doi.org/10.1111/josh.12540">https://doi.org/10.1111/josh.12540</a>  
DOI: <a href="https://doi.org/10.1111/josh.12540">https://doi.org/10.1111/josh.12540</a>
</p>
															<p>Souza, C. A., &amp; Andrade, T. C. (2018). Justiça social e saúde: Uma perspectiva sustentável. Revista de Políticas Públicas de Saúde, 22(3), 123–140. </p>
															<p>UNESCO. (2017). Education for Sustainable Development Goals: Learning objectives. UNESCO.  
DOI: <a href="https://doi.org/10.54675/CGBA9153">https://doi.org/10.54675/CGBA9153</a>
</p>
															<p>Vygotsky, L. (2007). A formação social da mente. Martins Fontes. </p>
															<p>Woellner, A. M., &amp; Grudzien, H. (2020). Higiene, ordem e saúde (2ª ed.). Cortez. </p>
																		</div>
				</section>
```


Entenda o processo acima e crie formas de extrais mais campos dos periódicos (Endereço, e-mail, telefone, Área, ISSN da versão impressa, ISSN da versão eletrônica, qualis, etc)

Entenda o processo acima e crie formas de extrais mais campos dos Artigos (Data da publicação, Data da submissão, Data da aceitação, DOI, número de páginas, Licença, Abstract, etc)
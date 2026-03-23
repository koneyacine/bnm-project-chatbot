# Guide de demo BNM Chatbot — Architecture separee
## URL principale : http://localhost:5175

## Parcours Client (2 min)
1. http://localhost:5175 → [Chat BNM]
2. Telephone : 22240001234 → Continuer
3. "Bonjour" → reponse directe
4. "Je veux ouvrir un compte" → VALIDATION
5. "Ma carte est bloquee" → RECLAMATION

## Parcours Agent (3 min)
1. http://localhost:5175 → [Espace Agent]
2. agent_reclamation / rec123 → Voir uniquement les reclamations
3. Cliquer ticket → Traiter → Valider
4. Se deconnecter → agent_validation / val123 → Voir uniquement les validations

## Comptes de demo
| Compte            | Mot de passe | Voit          |
|-------------------|--------------|---------------|
| agent_validation  | val123       | Validations   |
| agent_reclamation | rec123       | Reclamations  |
| agent_information | info123      | Informations  |
| Jiddou            | 1234         | Tout (Admin)  |
AVERTISSEMENT: Dev local uniquement

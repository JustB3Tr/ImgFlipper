package com.flipformat.viewer

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import com.flipformat.viewer.ui.FlipViewerApp
import com.flipformat.viewer.ui.theme.FlipViewerTheme

class MainActivity : ComponentActivity() {

    val cards = mutableStateListOf<FlipCard>()
    val selectedCard = mutableStateOf<FlipCard?>(null)
    val errorMessage = mutableStateOf<String?>(null)

    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        uri?.let { loadFlipFile(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        handleIntent(intent)

        setContent {
            FlipViewerTheme {
                FlipViewerApp(
                    cards = cards,
                    selectedCard = selectedCard.value,
                    errorMessage = errorMessage.value,
                    onOpenFilePicker = { openFilePicker() },
                    onSelectCard = { selectedCard.value = it },
                    onDismissError = { errorMessage.value = null },
                    onBackToGallery = { selectedCard.value = null },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent) {
        val uri = intent.data ?: return
        loadFlipFile(uri)
    }

    private fun openFilePicker() {
        filePickerLauncher.launch(arrayOf("*/*"))
    }

    private fun loadFlipFile(uri: Uri) {
        try {
            val card = FlipFileParser.parse(this, uri)
            cards.add(card)
            selectedCard.value = card
        } catch (e: Exception) {
            errorMessage.value = "Could not open file: ${e.message}"
        }
    }
}

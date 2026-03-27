package com.flipformat.viewer

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import org.json.JSONObject
import java.io.InputStream
import java.util.UUID
import java.util.zip.ZipInputStream

data class FlipCard(
    val id: String = UUID.randomUUID().toString(),
    val label: String,
    val frontBitmap: Bitmap,
    val backBitmap: Bitmap,
    val width: Int,
    val height: Int,
    val created: String,
)

data class FlipManifest(
    val format: String,
    val version: String,
    val created: String,
    val label: String,
    val frontFile: String,
    val backFile: String,
    val frontWidth: Int,
    val frontHeight: Int,
)

object FlipFileParser {

    fun parse(context: Context, uri: Uri): FlipCard {
        val inputStream = context.contentResolver.openInputStream(uri)
            ?: throw IllegalArgumentException("Cannot open file")
        return parse(inputStream, uri.lastPathSegment ?: "unknown.flip")
    }

    fun parse(inputStream: InputStream, fileName: String): FlipCard {
        val entries = mutableMapOf<String, ByteArray>()

        ZipInputStream(inputStream).use { zip ->
            var entry = zip.nextEntry
            while (entry != null) {
                if (!entry.isDirectory) {
                    entries[entry.name] = zip.readBytes()
                }
                zip.closeEntry()
                entry = zip.nextEntry
            }
        }

        val manifestBytes = entries["manifest.json"]
            ?: throw IllegalArgumentException("Missing manifest.json")

        val manifest = parseManifest(String(manifestBytes))

        if (manifest.format != "flip") {
            throw IllegalArgumentException("Not a .flip file (format=${manifest.format})")
        }

        val frontBytes = entries[manifest.frontFile]
            ?: throw IllegalArgumentException("Missing front image: ${manifest.frontFile}")
        val backBytes = entries[manifest.backFile]
            ?: throw IllegalArgumentException("Missing back image: ${manifest.backFile}")

        val frontBitmap = BitmapFactory.decodeByteArray(frontBytes, 0, frontBytes.size)
            ?: throw IllegalArgumentException("Corrupt front image")
        val backBitmap = BitmapFactory.decodeByteArray(backBytes, 0, backBytes.size)
            ?: throw IllegalArgumentException("Corrupt back image")

        return FlipCard(
            label = manifest.label.ifEmpty {
                fileName.removeSuffix(".flip")
            },
            frontBitmap = frontBitmap,
            backBitmap = backBitmap,
            width = manifest.frontWidth,
            height = manifest.frontHeight,
            created = manifest.created,
        )
    }

    private fun parseManifest(json: String): FlipManifest {
        val obj = JSONObject(json)
        val images = obj.getJSONObject("images")
        val front = images.getJSONObject("front")
        val back = images.getJSONObject("back")

        return FlipManifest(
            format = obj.getString("format"),
            version = obj.getString("version"),
            created = obj.optString("created", ""),
            label = obj.optJSONObject("object")?.optString("label", "") ?: "",
            frontFile = front.getString("file"),
            backFile = back.getString("file"),
            frontWidth = front.getInt("width"),
            frontHeight = front.getInt("height"),
        )
    }
}

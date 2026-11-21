#import <Foundation/Foundation.h>
#import <iTunesLibrary/ITLibrary.h>
#import <iTunesLibrary/ITLibMediaItem.h>
#import <iTunesLibrary/ITLibArtist.h>
#import <iTunesLibrary/ITLibAlbum.h>
#import <iTunesLibrary/ITLibPlaylist.h>

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSString *outputPath = nil;
        for (int i = 1; i < argc; i++) {
            NSString *arg = [NSString stringWithUTF8String:argv[i]];
            if ([arg isEqualToString:@"--out"] && i + 1 < argc) {
                outputPath = [NSString stringWithUTF8String:argv[++i]];
            }
        }

        NSError *error = nil;
        ITLibrary *library = [ITLibrary libraryWithAPIVersion:@"1.0" error:&error];
        if (!library) {
            NSDictionary *errDict = @{
                @"sucesso": @NO,
                @"erro": [NSString stringWithFormat:@"Não foi possível conectar ao Apple Music: %@", error ? error.localizedDescription : @"Erro desconhecido"]
            };
            NSData *jsonData = [NSJSONSerialization dataWithJSONObject:errDict options:NSJSONWritingPrettyPrinted error:nil];
            if (outputPath) {
                [jsonData writeToFile:outputPath atomically:YES];
            } else {
                [[NSFileHandle fileHandleWithStandardOutput] writeData:jsonData];
            }
            return 1;
        }

        NSMutableArray *tracksList = [NSMutableArray array];
        for (ITLibMediaItem *item in library.allMediaItems) {
            if (item.mediaKind != ITLibMediaItemMediaKindSong) {
                continue;
            }
            NSString *filePath = item.location ? [item.location path] : @"";
            if (!filePath || [filePath length] == 0) {
                continue;
            }

            NSMutableDictionary *trackDict = [NSMutableDictionary dictionary];
            [trackDict setObject:[item.persistentID stringValue] ?: @"" forKey:@"id"];
            [trackDict setObject:item.title ?: @"" forKey:@"title"];
            [trackDict setObject:item.artist.name ?: @"" forKey:@"artist"];
            [trackDict setObject:item.album.title ?: @"" forKey:@"album"];
            [trackDict setObject:item.album.albumArtist ?: @"" forKey:@"album_artist"];
            [trackDict setObject:item.genre ?: @"" forKey:@"genre"];
            [trackDict setObject:@(item.totalTime) forKey:@"duration_ms"];
            [trackDict setObject:@(item.beatsPerMinute) forKey:@"bpm"];
            [trackDict setObject:@(item.year) forKey:@"year"];
            [trackDict setObject:@(item.rating) forKey:@"rating"];
            [trackDict setObject:@(item.playCount) forKey:@"play_count"];
            [trackDict setObject:filePath forKey:@"filepath"];
            [trackDict setObject:@(item.fileSize) forKey:@"file_size"];
            [trackDict setObject:@(item.bitrate) forKey:@"bitrate"];
            [trackDict setObject:@(item.sampleRate) forKey:@"sample_rate"];

            [tracksList addObject:trackDict];
        }

        NSMutableArray *playlistsList = [NSMutableArray array];
        for (ITLibPlaylist *pl in library.allPlaylists) {
            if (pl.isMaster) {
                continue;
            }
            NSMutableArray *trackIds = [NSMutableArray array];
            for (ITLibMediaItem *item in pl.items) {
                if (item.persistentID) {
                    [trackIds addObject:[item.persistentID stringValue]];
                }
            }
            [playlistsList addObject:@{
                @"id": [pl.persistentID stringValue] ?: @"",
                @"name": pl.name ?: @"Sem Nome",
                @"track_ids": trackIds,
                @"count": @([trackIds count])
            }];
        }

        NSDictionary *outputDict = @{
            @"sucesso": @YES,
            @"total_tracks": @([tracksList count]),
            @"total_playlists": @([playlistsList count]),
            @"playlists": playlistsList,
            @"tracks": tracksList
        };

        NSData *jsonData = [NSJSONSerialization dataWithJSONObject:outputDict options:NSJSONWritingPrettyPrinted error:&error];
        if (!jsonData) {
            NSLog(@"Erro ao serializar JSON: %@", error);
            return 1;
        }

        if (outputPath) {
            BOOL ok = [jsonData writeToFile:outputPath atomically:YES];
            if (!ok) {
                NSLog(@"Falha ao gravar arquivo em %@", outputPath);
                return 1;
            }
        } else {
            [[NSFileHandle fileHandleWithStandardOutput] writeData:jsonData];
        }
    }
    return 0;
}
